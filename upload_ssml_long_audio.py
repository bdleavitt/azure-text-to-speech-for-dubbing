    ## Submit the SSML for processing.
    get_synthesized_speech_from_ssml(
        ssml=ssml_string,
        voice_name=voice_name,
        voice_language=voice_language,
        service_region=service_region,
        speech_key=speech_key,
        output_filename=os.path.join(output_directory, 'synthesized_voice_finalized_audio.wav')
    )

