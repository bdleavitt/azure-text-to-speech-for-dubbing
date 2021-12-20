#!/usr/bin/env python3
import os
import argparse
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
import random
import string
import azure.cognitiveservices.speech as speechsdk
import wave
import contextlib
import xml.etree.ElementTree as xml
import shutil

from rich import pretty
pretty.install()

def combine_ttml_to_sentences(ttml_file_path):
    ## combine phrases into more complete sentences, which will be more natural for the speech synthesis
    with open(ttml_file_path, 'r', encoding="utf-8") as f:
        ttml_doc = f.read()
        soup = BeautifulSoup(ttml_doc, features="html.parser")

    captions = soup.select('p')

    sentences_list = []
    sentence_dict = {'text': '', 'begin': '', 'end': ''}

    for phrase in captions:
        ## get the first timestamp the first time through
        if not sentence_dict['begin']:
            sentence_dict['begin'] = phrase['begin']
        else: 
            sentence_dict['begin'] = min(phrase['begin'], sentence_dict['begin'])
        
        ## get the largest end timestamp in the sentence. 
        sentence_dict['end'] = max(phrase['end'], sentence_dict['end'])
        
        ## add the sentence to the dict
        if not sentence_dict['text']:
            sentence_dict['text'] = phrase.text.strip()
        else:
            sentence_dict['text'] = sentence_dict['text'] + " " + phrase.text.strip()

        ## If this is the end of a sentence, add it to the list of sentences
        if phrase.text[-1] in ".!?":
            begin = datetime.strptime(sentence_dict["begin"], "%H:%M:%S.%f")
            end = datetime.strptime(sentence_dict["end"], "%H:%M:%S.%f")
            duration = end - begin
            sentence_dict['target_duration'] = duration.total_seconds()
            sentence_dict['character_length'] = len(sentence_dict['text'])

            sentences_list.append(sentence_dict)
            sentence_dict = {'text': '', 'begin': '', 'end': ''}     

    return sentences_list

def calculate_duration(wave_filename):
    with contextlib.closing(wave.open(wave_filename, 'r')) as f:
        frames = f.getnframes()
        rate = f.getframerate()
        duration = frames / float(rate)

    return duration

def check_speech_result(result, text):
    from azure.cognitiveservices.speech import ResultReason, CancellationReason
    if result.reason == ResultReason.SynthesizingAudioCompleted:
        print("Speech synthesized to speaker for text [{}]".format(text))
    elif result.reason == ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print("Speech synthesis canceled: {}".format(cancellation_details.reason))
        if cancellation_details.reason == CancellationReason.Error:
            if cancellation_details.error_details:
                print("Error details: {}".format(cancellation_details.error_details))
        print("Did you update the subscription info?")

def get_synthesized_speech(text, voice_name, voice_language, output_filename, speech_key, service_region):
    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
    speech_config.speech_synthesis_language = voice_language
    speech_config.speech_synthesis_voice_name = voice_name
    audio_config = speechsdk.AudioConfig(filename=output_filename)
    speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    resp = speech_synthesizer.speak_text_async(text).get()
    check_speech_result(resp, text)

def get_synthesized_speech_from_ssml(ssml, voice_name, voice_language, output_filename, speech_key, service_region):
    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
    speech_config.speech_synthesis_language = voice_language
    speech_config.speech_synthesis_voice_name = voice_name
    audio_config = speechsdk.AudioConfig(filename=output_filename)
    speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    resp = speech_synthesizer.speak_ssml_async(ssml).get()


def pre_process_audio_snippets(sentences_list, voice_name, voice_language, audio_staging_directory, service_region, speech_key, prefix):
    for i, sentence in enumerate(sentences_list):
        filename = f"{audio_staging_directory}/{prefix}_{i}.wav"
        sentences_list[i]['audio_file'] = filename    
        get_synthesized_speech(
            text=sentence['text'], 
            voice_name=voice_name, 
            voice_language=voice_language, 
            output_filename=filename, 
            service_region=service_region, 
            speech_key=speech_key
        )
        sentences_list[i]['actual_duration'] = calculate_duration(sentence['audio_file'])
        sentences_list[i]["phrase_prosody_rate"] = sentences_list[i]["target_duration"] / sentences_list[i]["actual_duration"]

    return sentences_list

def generate_ssml_breaks(parent_xml, break_length_in_sec) -> xml.Element:
    max_break_length_in_sec = 5
    num_full_breaks = int(break_length_in_sec // max_break_length_in_sec)
    remainder_break_length_in_sec = break_length_in_sec % max_break_length_in_sec

    if num_full_breaks == 0:
        break_list = [remainder_break_length_in_sec]
    else:
        break_list = [5] * num_full_breaks
        if remainder_break_length_in_sec > 0:
            break_list.append(remainder_break_length_in_sec)

    for b in break_list:
        ## insert code to add a break here.
        brk_ms = int(b * 1000)
        brk = xml.Element("break", attrib={"time":f"{brk_ms}"})
        parent_xml.append(brk)

def build_ssml(sentences_list, voice_name, voice_language, output_path, adjust_rate = False):
    ## Build the XML tree for SSML
    root = xml.Element("speak", attrib={'version':'1.0', 'xmlns':'http://www.w3.org/2001/10/synthesis', 'xml:lang': f'{voice_language}'})
    voice_element = xml.Element('voice', attrib={'name':f'{voice_name}'})
    root.append(voice_element)

    # latest_timestamp = datetime.strptime("00:00:00.000", "%H:%M:%S.%f")
    # next_timestamp = datetime.strptime("00:00:00.000", "%H:%M:%S.%f")
    accumulated_overage_time = 0
    
    ## Insert starting break
    file_start = datetime.strptime("00:00:00.000", "%H:%M:%S.%f")
    first_time_stamp = datetime.strptime(sentences_list[0]['begin'], "%H:%M:%S.%f")
    starting_break_sec = (first_time_stamp - file_start).total_seconds()
    generate_ssml_breaks(voice_element, starting_break_sec)

    ## for each sentence, generate the objects and corresponding breaks
    for sentence in sentences_list:

        # ## Put any breaks that precede the sentence
        # next_timestamp = datetime.strptime(sentence['begin'], "%H:%M:%S.%f")
        # if next_timestamp > latest_timestamp:
        #     pre_break_time = next_timestamp - latest_timestamp
        #     pre_break_time_sec = pre_break_time.total_seconds() + accumulated_overage_time
        #     if pre_break_time_sec > 0:
        #         generate_ssml_breaks(voice_element, pre_break_time_sec)
        #         accumulated_overage_time = 0
        #     else:
        #         accumulated_overage_time += pre_break_time_sec

        # latest_timestamp = next_timestamp

        ## Create the sentence
        # sentence_element = xml.Element("s", attrib={"duration": str(int(sentence['actual_duration']*1000))})
        sentence_element = xml.Element("s")
        sentence_element.text = sentence['text']
        voice_element.append(sentence_element) 
        non_break_element = xml.Element('break', attrib={'strength': 'none'})
        voice_element.append(non_break_element)

        ## Put any breaks needed after the sentence        
        sentence_gap_in_sec = sentence['target_duration'] - sentence['actual_duration']
        if sentence_gap_in_sec >= 0: ## if the generated audio is shorter than the target audio
            
            ## Add the appropriate filler gap, removing any accumulated overages
            ## Ex sentence gap is 3.5 seconds
            ## Accumulated gap is -7.5 seconds
            ## break_duration = 3.5 seconds + -7.5 seconds = -4 seconds
            break_duration = sentence_gap_in_sec + accumulated_overage_time

            if break_duration > 0:
                ## create breaks, zero out the accumulated time
                generate_ssml_breaks(voice_element, sentence_gap_in_sec)
                accumulated_overage_time = 0
            else: 
                ## otherwise, just update the accumulated overage time
                ## skip creating a break
                accumulated_overage_time = break_duration
        else:
            accumulated_overage_time =+ sentence_gap_in_sec        

    tree = xml.ElementTree(root)
    tree.write(output_path, encoding='utf-8')
    ssml_string = str(xml.tostring(root, encoding='utf-8'), encoding='utf-8')
    print(ssml_string)
    return ssml_string

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser()

    parser.add_argument('-i', '--infile', type=str, help='input ttml file path')
    parser.add_argument('-o', '--outputdirectory', type=str, default="output", help='output ssml file path')
    parser.add_argument('-v', '--voice', required=False, type=str)
    parser.add_argument('-l', '--language', required=False, type=str)
    parser.add_argument('-p', '--prefix', default="".join(random.choices(string.ascii_letters, k=3)), type=str)
    parser.add_argument('-r', '--rateadjust', default=1.0, type=float)
    parser.add_argument('-s', '--stagingdir', default='audio_outputs', type=str)

    args = parser.parse_args()

    # input_ttml = args.infile
    input_ttml = args.infile 
    output_directory = args.outputdirectory
    prefix = args.prefix
    voice_name = args.voice
    voice_language = args.language
    staging_directory = args.stagingdir

    output_ssml = os.path.join(output_directory, 'generated_ssml.xml')

    ## load values from the .env file
    load_dotenv()

    if not (input_ttml):
        try:
            input_ttml = os.environ['INPUT_TTML_PATH']
        except Exception as e:
            print("You must provide an input path as command line arguements, or as an environment variable.")
            raise e 

    if not (voice_language and voice_name):
        try:
            voice_name = os.environ['VOICE_NAME']
            voice_language = os.environ['VOICE_LANGUAGE']
        except Exception as e:
            print("You will need to provide a valid voice name and voice language/locale as a command line argument or as an environment variable.")
            raise e 

    try:
        speech_key = os.environ['SPEECH_KEY']
        service_region = os.environ['SERVICE_REGION']
    except Exception as e:
        print("You must provide a SPEECH_KEY and SERVICE_REGION as an environment variable or .env file.")
        raise e

    ## Run the stuff. 
    ## Clear the staging directory, then recreate it
    os.makedirs(output_directory, exist_ok=True)

    staging_directory = os.path.join(output_directory, staging_directory)

    if os.path.exists(staging_directory):
        shutil.rmtree(staging_directory)

    os.makedirs(staging_directory, exist_ok=True)

    ## Combine the captions into complete sentences
    combined_sentences = combine_ttml_to_sentences(input_ttml)

    ## Process the sentences to get the estimated audio lengths, and generate prosody rates as needed. 
    processed_sentences = pre_process_audio_snippets(
        combined_sentences, 
        voice_name=voice_name,
        voice_language=voice_language,
        audio_staging_directory=staging_directory,
        prefix = prefix,
        service_region=service_region,
        speech_key=speech_key
    )

    with open(os.path.join(output_directory, "sentences_list.txt"), "w") as f:
        f.write(str(processed_sentences))

    ## Use the processed data to generate an SSML document (writes to file)
    ssml_string = build_ssml(
        sentences_list=processed_sentences,
        voice_name=voice_name,
        voice_language=voice_language,
        output_path=output_ssml
    )
    
    if ssml_string:
        print(f"Completed generating SSML. {output_ssml}")