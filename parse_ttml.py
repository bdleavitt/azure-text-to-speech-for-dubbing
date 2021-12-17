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
        filename = f"{audio_staging_directory}/{prefix}_{i}.wav" # !! TODO rename this
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

def build_ssml(sentences_list, voice_name, voice_language, output_path):
    ## Build the XML tree for SSML
    root = xml.Element("speak", attrib={'version':'1.0', 'xmlns':'http://www.w3.org/2001/10/synthesis', 'xml:lang': f'{voice_language}'})
    voice_element = xml.Element('voice', attrib={'name':f'{voice_name}'})
    root.append(voice_element)

    latest_timestamp = datetime.strptime("00:00:00.000", "%H:%M:%S.%f")
    next_timestamp = datetime.strptime("00:00:00.000", "%H:%M:%S.%f")

    for sentence in sentences_list:
        next_timestamp = datetime.strptime(sentence['begin'], "%H:%M:%S.%f")
        if next_timestamp > latest_timestamp:
            ## get the time needed for the break
            break_time = next_timestamp - latest_timestamp
            break_time_sec = break_time.total_seconds()
            
            ## create a break element(s) based on the gap, with a max of 5 seconds
            max_break = [5]
            num_breaks = break_time_sec // max_break[0]
            break_list = [pause_break for pause_break in max_break for i in range(int(num_breaks))]
            break_list.append(break_time_sec % max_break[0])

            for b in break_list:
                ## insert code to add a break here.
                brk_ms = int(b * 1000)
                brk = xml.Element("break", attrib={"time":f"{brk_ms}"})
                voice_element.append(brk)
            
            latest_timestamp = datetime.strptime(sentence['end'], "%H:%M:%S.%f")

        ## insert code to add a sentence here
        #s = xml.Element("s")
        #s.text = sentence['text']
        prosody = xml.Element("prosody", attrib={'rate':f"{round(sentence['phrase_prosody_rate'], 2)}"})
        #s.text = sentence['text']
        prosody.text = sentence['text']
        voice_element.append(prosody)

    tree = xml.ElementTree(root)
    tree.write(output_path, encoding='utf-8')
    return True

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser()

    parser.add_argument('-i', '--infile', type=str, help='input ttml file path')
    parser.add_argument('-o', '--outfile', type=str, default="generated_ssml.xml", help='output ssml file path')
    parser.add_argument('-v', '--voice', required=False, type=str)
    parser.add_argument('-l', '--language', required=False, type=str)
    parser.add_argument('-p', '--prefix', default="".join(random.choices(string.ascii_letters, k=3)), type=str)
    parser.add_argument('-s', '--stagingdir', default=f'audio_outputs', type=str)
    
    args = parser.parse_args()

    input_ttml = args.infile
    output_ssml = args.outfile
    prefix = args.prefix
    voice_name = args.voice
    voice_language = args.language
    staging_directory = args.stagingdir
    
    ## load values from the .env file
    load_dotenv()

    if not (input_ttml and output_ssml):
        try:
            input_ttml = os.environ['INPUT_TTML_PATH']
            output_ssml = os.environ['OUTPUT_SSML_PATH']
        except Exception as e:
            print("You must provide an input and output path as command line arguements, or as an environment variable.")
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
    ## Use the processed data to generate an SSML document (writes to file)
    if build_ssml(
        sentences_list=processed_sentences,
        voice_name=voice_name,
        voice_language=voice_language,
        output_path=output_ssml
    ):
        print(f"Completed generating SSML. {output_ssml}")
    ## Read the SSML back in
    with open(output_ssml, 'r', encoding='utf-8') as f:
        ssml_string = f.read()
    ## Submit the SSML for processing.
    get_synthesized_speech_from_ssml(
        ssml=ssml_string,
        voice_name=voice_name,
        voice_language=voice_language,
        service_region=service_region,
        speech_key=speech_key,
        output_filename=f'{prefix}_{output_ssml}_finalized_audio.wav'
    )