from audioop import avg
import os
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
import json
import string
import azure.cognitiveservices.speech as speechsdk
import wave
import contextlib
import xml.etree.ElementTree as xml
import shutil
import random

class TTMLConverter:
    def __init__(self, ttml_text = None, ttml_file_path = None, output_staging_directory = None, prefix = 'tts'):
        self.speech_key = ""
        self.service_region = ""
        self.voice_name = ""
        self.voice_language = ""
        self.prefix = prefix
        self.target_audio_format = 'Riff16Khz16BitMonoPcm'
        if ttml_file_path is not None:
            with open(ttml_file_path, 'r', encoding="utf-8") as f:
                self.ttml_text = f.read()
        elif ttml_text is not None:
            self.ttml_text = ttml_text
        else:
            raise AttributeError("You must provide either a file path or a string value for your TTML input.") 
        
        if output_staging_directory is None:
            now_string = datetime.strftime(datetime.now(), "%Y%m%d_%H%M%S")
            self.output_staging_directory = os.path.join('outputs', now_string)
        else:
            self.output_staging_directory = os.path.join('outputs', output_staging_directory)

        ## clear the staging directory and create it
        if os.path.exists(self.output_staging_directory):
            shutil.rmtree(self.output_staging_directory) 
        
        os.makedirs(self.output_staging_directory)

        ## Copy the starting TTML to the target directory
        new_ttml_path = os.path.join('./', self.output_staging_directory, 'starting_text.ttml')
        with open(new_ttml_path, 'w', encoding='utf-8') as f:
            f.write(self.ttml_text)

    def combine_ttml_to_sentences(self):
        self.sentences_list = []
        sentences_list = []
        sentence_dict = {'text': '', 'begin': '', 'end': ''}
        soup = BeautifulSoup(self.ttml_text, features="html.parser")
        captions = soup.select('p')
              
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

        self.sentences_list = sentences_list
        return sentences_list

    def pre_process_audio_snippets(self, sentences_list, clip_audio_directory="preprocessed", avg_prosody_rate=1):
        temp_audio_folder_path = os.path.join(self.output_staging_directory, clip_audio_directory)
        os.makedirs(temp_audio_folder_path, exist_ok=True)

        for i, sentence in enumerate(sentences_list):
            filename = os.path.join(temp_audio_folder_path, f"{self.prefix}_{i}.wav")
            print(filename)
            sentences_list[i]['audio_file'] = filename
            
            ## get the SSML for the sentence
            phrase_ssml = self.build_ssml([sentence], insert_breaks=False, output_files = False, prosody_rate=avg_prosody_rate)
            sentences_list[i]['phrase_ssml'] = phrase_ssml
            
            speech_synthesizer = self.get_speech_synthesizer(filename, )
            print(f"This is the phrase_ssml: {phrase_ssml}")
            resp = speech_synthesizer.speak_ssml_async(phrase_ssml).get()
            
            self.check_speech_result(resp, phrase_ssml)

            sentences_list[i]['actual_duration'] = self.calculate_duration(sentence['audio_file'])       
        
        self.sentences_list = sentences_list
        return sentences_list

    def output_sentences_list(self, file_name):
        path = os.path.join(self.output_staging_directory, file_name)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(self.sentences_list, indent=4))

    def calculate_prosody_rates(self, sentences_list):
        return_dict = {}
        for i, sentence in enumerate(sentences_list):
            sentences_list[i]["phrase_prosody_rate"] = sentences_list[i]["actual_duration"] / sentences_list[i]["target_duration"]

        prosody_rates = [sentence['phrase_prosody_rate'] for sentence in sentences_list]
        avg_prosody_rate = sum(prosody_rates) / len(prosody_rates)
        
        ## if the synthesized voice is already talking on average faster than the source voice,
        ## don't change the rate. We will use breaks to maintain the timing. 
        if avg_prosody_rate > 1:
            avg_prosody_rate = 1
        
        return_dict['avg_prosody'] = avg_prosody_rate
        return_dict['prosody_rates'] = prosody_rates
        return_dict['list'] = sentences_list
        self.sentences_list = sentences_list
        
        return return_dict

    def calculate_duration(self, wave_filename):
        with contextlib.closing(wave.open(wave_filename, 'r')) as f:
            frames = f.getnframes()
            rate = f.getframerate()
            duration = frames / float(rate)
        return duration

    def break_sentences_into_batches(self, sentences_list, batch_min_mark=5):
        ## break the transcript into 5 minutes at a time (to avoid the 10 minute audio limit of the invidual synthesis)
        sentence_batch_lists = {}
        batch_num = 0
        time_start = datetime.strptime("00:00:00.000", "%H:%M:%S.%f")

        for sentence in sentences_list: 
            t = datetime.strptime(sentence['end'], "%H:%M:%S.%f")
            delta = t - time_start
            batch_num = int(delta.total_seconds() / 60 // int(batch_min_mark))    
            if batch_num not in sentence_batch_lists.keys():
                sentence_batch_lists[batch_num] = []
            sentence_batch_lists[batch_num].append(sentence)
        print(f"Breaking sentences into {len(sentence_batch_lists.items())} batches.")
        return sentence_batch_lists

    def generate_ssml_breaks(self, parent_xml, break_length_in_sec) -> xml.Element:
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

    def build_ssml(self, 
        sentences_list, 
        insert_breaks=True, 
        output_files=True, 
        output_file_num = None, 
        prosody_rate = 1, 
        file_start="00:00:00.000"
        ):
        ## Build the XML tree for SSML
        root = xml.Element("speak", attrib={'version':'1.0', 'xmlns':'http://www.w3.org/2001/10/synthesis', 'xml:lang': f'{self.voice_language}'})
        voice_element = xml.Element('voice', attrib={'name':f'{self.voice_name}'})
        root.append(voice_element)
        prosody_element = xml.Element('prosody', attrib={'rate':f'{prosody_rate}'})
        voice_element.append(prosody_element)

        # latest_timestamp = datetime.strptime("00:00:00.000", "%H:%M:%S.%f")
        # next_timestamp = datetime.strptime("00:00:00.000", "%H:%M:%S.%f")
        accumulated_overage_time = 0
        
        ## Insert starting break
        if insert_breaks == True:
            file_start = datetime.strptime(file_start, "%H:%M:%S.%f")
            first_time_stamp = datetime.strptime(sentences_list[0]['begin'], "%H:%M:%S.%f")
            starting_break_sec = (first_time_stamp - file_start).total_seconds()
            
            ## Put any breaks that precede the sentence
            self.generate_ssml_breaks(prosody_element, starting_break_sec)

        ## for each sentence, generate the objects and corresponding breaks
        for sentence in sentences_list:
            ## Create the sentence
            # sentence_element = xml.Element("s", attrib={"duration": str(int(sentence['actual_duration']*1000))})
            sentence_element = xml.Element("s")
            sentence_element.text = sentence['text']
            prosody_element.append(sentence_element) 
            non_break_element = xml.Element('break', attrib={'strength': 'none'})
            prosody_element.append(non_break_element)

            if insert_breaks == True:
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
                        self.generate_ssml_breaks(prosody_element, sentence_gap_in_sec)
                        accumulated_overage_time = 0
                    else: 
                        ## otherwise, just update the accumulated overage time
                        ## skip creating a break
                        accumulated_overage_time = break_duration
                else:
                    accumulated_overage_time =+ sentence_gap_in_sec        
            
        ssml_string = str(xml.tostring(root, encoding='utf-8'), encoding='utf-8')
        
        ## output files
        if output_files == True:
            ssml_output_path = os.path.join(self.output_staging_directory, f"{output_file_num}_output_ssml.xml")
            with open(ssml_output_path, 'w', encoding='utf-8') as f:
                f.write(ssml_string)

        return ssml_string

    def check_speech_result(self,result, text):
        from azure.cognitiveservices.speech import ResultReason, CancellationReason
        if result.reason == ResultReason.SynthesizingAudioCompleted:
            print("Speech synthesized for text [{}]".format(text))
        elif result.reason == ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print("Speech synthesis canceled: {}".format(cancellation_details.reason))
            print("Supplied text was ", text)
            if cancellation_details.reason == CancellationReason.Error:
                if cancellation_details.error_details:
                    print("Error details: {}".format(cancellation_details.error_details))
            print("Did you update the subscription info?")
    
    def get_speech_synthesizer(self, output_filename = None, speech_synthesis_output_format = None):
        speech_config = speechsdk.SpeechConfig(subscription=self.speech_key, region=self.service_region)
        speech_config.speech_synthesis_language = self.voice_language
        speech_config.speech_synthesis_voice_name = self.voice_name
        ## TODO: take the output audio format as a parameter
        if not speech_synthesis_output_format:
            speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat[self.target_audio_format])
        else:
            speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat[speech_synthesis_output_format])
        if not output_filename:
            audio_filename = f"{self.voice_language}_generated_audio.mp3"
            output_filename = os.path.join(self.output_staging_directory, audio_filename)
        audio_config = speechsdk.audio.AudioConfig(filename=output_filename)
        speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
        return speech_synthesizer

    def get_synthesized_speech(self, text, voice_name, voice_language, output_filename, speech_key, service_region):
        speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
        speech_config.speech_synthesis_language = voice_language
        speech_config.speech_synthesis_voice_name = voice_name
        audio_config = speechsdk.AudioConfig(filename=output_filename)
        speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
        resp = speech_synthesizer.speak_text_async(text).get()
        self.check_speech_result(resp, text)