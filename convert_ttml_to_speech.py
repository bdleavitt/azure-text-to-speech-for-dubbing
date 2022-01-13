import os
import argparse
import random
import string

from ttml2speech.TTMLConverter import TTMLConverter
from dotenv import load_dotenv
from rich import pretty
pretty.install()


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    ## Read environment file values first
    load_dotenv()
    speech_key = os.environ['SPEECH_KEY']
    service_region = os.environ['SERVICE_REGION']
        
    ## Define Command Line Args
    parser.add_argument('-i', '--infile', type=str, help='input ttml file path')
    parser.add_argument('-o', '--outputdirectory', type=str, default="output", help='output directory')
    parser.add_argument('-v', '--voice', required=False, default=None, type=str)
    parser.add_argument('-l', '--language', required=False, default=None, type=str)
    parser.add_argument('-p', '--prefix', default="".join(random.choices(string.ascii_letters, k=3)), type=str)

    args = parser.parse_args()

    ## Assing command line args
    # input_ttml = args.infile
    input_ttml = args.infile 
    output_directory = args.outputdirectory
    prefix = args.prefix
    voice_name = args.voice if args.voice else os.environ['VOICE_NAME']
    voice_language = args.language if args.language else os.environ['VOICE_LANGUAGE']
    
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



    ## Run the Stuff
    ## Create the TTML Converter Object
    my_converter = TTMLConverter(ttml_file_path=input_ttml, output_staging_directory=output_directory, prefix=prefix)

    ## If command line args are provided, use those instead of the env file. 
    my_converter.speech_key = speech_key
    my_converter.service_region = service_region
    my_converter.voice_name = voice_name
    my_converter.voice_language = voice_language

    sentences_list = my_converter.combine_ttml_to_sentences()

    sentences_list = my_converter.pre_process_audio_snippets(
        sentences_list=sentences_list
    )

    ## Get determine the rate to apply to hte voice to most closely match the original. 
    ## Then Re-preprocess audio snippet but include the average prosody rate
    adjustments_dict = my_converter.calculate_prosody_rates(sentences_list=sentences_list)

    avg_prosody_rate = adjustments_dict['avg_prosody']
    prosody_rates = adjustments_dict['prosody_rates']

    optimized_sentences_list = my_converter.pre_process_audio_snippets(sentences_list, clip_audio_directory='prosody_adjusted', avg_prosody_rate=round(avg_prosody_rate, 1))

    ## write out the sentences list to file
    my_converter.output_sentences_list('enriched_sentences.json')

    ## generate the ssml for each the created batches and submit the ssml to the audio for processing
    ## using the same target file and audio config which should allow us to exceed the 10 minute limit. 
    sentence_batch_dict = my_converter.break_sentences_into_batches(sentences_list, batch_min_mark=5)
    speech_synthesizer = my_converter.get_speech_synthesizer(speech_synthesis_output_format='Audio24Khz96KBitRateMonoMp3')

    start_file_time = "00:00:00.000"
    for index, batch in sentence_batch_dict.items():
        print(f"Generating and submitting SSML for batch {index}")
        batch_ssml = ""
        batch_ssml = my_converter.build_ssml(batch, output_file_num=index, file_start=start_file_time)
        start_file_time = batch[-1]['end']
        res = speech_synthesizer.speak_ssml_async(batch_ssml).get()
        my_converter.check_speech_result(res, f"SSML for batch {index}")