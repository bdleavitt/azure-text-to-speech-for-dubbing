import os
from azure.identity import ClientSecretCredential
from azure.mgmt.media import AzureMediaServices
from dotenv import load_dotenv
from rich import pretty
from pprint import pprint
load_dotenv()
pretty.install()


tenant_id = os.environ['TENANT_ID']
client_id=os.environ['CLIENT_ID']
client_secret = os.environ['CLIENT_SECRET']
subscription_id = os.environ['SUBSCRIPTION_ID']
rg_name = os.environ['RESOURCE_GROUP_NAME']
media_services_account_name = os.environ['MEDIA_SERVICES_ACCOUNT_NAME']

credentials = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
client = AzureMediaServices(credential=credentials, subscription_id=subscription_id)


## Create a transformation for audio only conversion



# import os
# from datetime import datetime
# from azure.cognitiveservices import speech
# from azure.cognitiveservices.speech import speech_py_impl
# from ttml2speech.TTMLConverter import TTMLConverter




# my_converter = TTMLConverter(ttml_file_path=".\\james_pace.\\james_pace_spanish_for_real.ttml", output_staging_directory="hopefully_final")

# my_converter.speech_key = os.environ['SPEECH_KEY']
# my_converter.service_region = os.environ['SERVICE_REGION']
# my_converter.voice_name = os.environ['VOICE_NAME']
# my_converter.voice_language = os.environ['VOICE_LANGUAGE']

# sentences_list = my_converter.combine_ttml_to_sentences()

# sentences_list = my_converter.pre_process_audio_snippets(
#     sentences_list=sentences_list
# )

# ## Get determine the rate to apply to hte voice to most closely match the original. 
# ## Then Re-preprocess audio snippet but include the average prosody rate
# adjustments_dict = my_converter.calculate_prosody_rates(sentences_list=sentences_list)

# avg_prosody_rate = adjustments_dict['avg_prosody']
# prosody_rates = adjustments_dict['prosody_rates']

# optimized_sentences_list = my_converter.pre_process_audio_snippets(sentences_list, clip_audio_directory='prosody_adjusted', avg_prosody_rate=round(avg_prosody_rate, 1))

# ## write out the sentences list to file
# my_converter.output_sentences_list('enriched_sentences.json')

# ## generate the ssml for each the created batches and submit the ssml to the audio for processing
# ## using the same target file and audio config which should allow us to exceed the 10 minute limit. 
# sentence_batch_dict = my_converter.break_sentences_into_batches(sentences_list, batch_min_mark=5)
# speech_synthesizer = my_converter.get_speech_synthesizer(speech_synthesis_output_format='Audio24Khz96KBitRateMonoMp3')

# start_file_time = "00:00:00.000"
# for index, batch in sentence_batch_dict.items():
#     print(f"Generating and submitting SSML for batch {index}")
#     batch_ssml = ""
#     batch_ssml = my_converter.build_ssml(batch, output_file_num=index, file_start=start_file_time)
#     start_file_time = batch[-1]['end']
#     res = speech_synthesizer.speak_ssml_async(batch_ssml).get()
#     my_converter.check_speech_result(res, f"SSML for batch {index}")