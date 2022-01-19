import os, uuid, sys
import time #Timer for checking job progress
import random #This is only necessary for the random number generation


from azure.identity import DefaultAzureCredential
from azure.mgmt.media import AzureMediaServices
from azure.storage.blob import BlobServiceClient, BlobClient
from azure.mgmt.media.models import (
  Asset,
  Transform,
  TransformOutput,
  BuiltInStandardEncoderPreset,
  Job,
  JobInputAsset,
  JobOutputAsset
)

from dotenv import load_dotenv
from rich import pretty
from pprint import pprint

load_dotenv()
pretty.install()

tenant_id = os.environ['TENANT_ID']
client_id=os.environ['AADCLIENTID']
client_secret = os.environ['AADSECRET']
subscription_id = os.environ['SUBSCRIPTION_ID']
resource_group_name = os.environ['RESOURCE_GROUP_NAME']
account_name = os.environ['MEDIA_SERVICES_ACCOUNT_NAME']


#### STORAGE ####
# Values from .env and the blob url
# For this sample you will use the storage account connection string to create and access assets
storage_account_connection = os.getenv('STORAGEACCOUNTCONNECTION')

# Get the default Azure credential from the environment variables AADCLIENTID and AADSECRET
default_credential = DefaultAzureCredential()

# The file you want to upload.  For this example, put the file in the same folder as this script. 
# The file ignite.mp4 has been provided for you. 
source_file_directory = "pace_output_2"
source_file_name = "generated_audio.mp3"
asset_name = "james_pace_english_with_breaks"

# Generate a random number that will be added to the naming of things so that you don't have to keep doing this during testing.
uniqueness = random.randint(0,9999)

# Set the attributes of the input Asset using the random number
in_asset_name = asset_name + '_in_' + str(uniqueness)
in_alternate_id = 'inputALTid' + str(uniqueness)
in_description = 'James Pace speaking spanish, in english, with the breaks.' + str(uniqueness)
# Create an Asset object
# From the SDK
# Asset(*, alternate_id: str = None, description: str = None, container: str = None, storage_account_name: str = None, **kwargs) -> None
# The asset_id will be used for the container parameter for the storage SDK after the asset is created by the AMS client.
input_asset = Asset(alternate_id=in_alternate_id,description=in_description)

# Set the attributes of the output Asset using the random number
out_asset_name = 'james_pace_english' + '_out_' + str(uniqueness)
out_alternate_id = 'outputALTid' + str(uniqueness)
out_description = 'james_pace_english' + str(uniqueness)
# From the SDK
# Asset(*, alternate_id: str = None, description: str = None, container: str = None, storage_account_name: str = None, **kwargs) -> None
output_asset = Asset(alternate_id=out_alternate_id,description=out_description)

# The AMS Client
print("Creating AMS client")
# From SDK
# AzureMediaServices(credentials, subscription_id, base_url=None)
client = AzureMediaServices(default_credential, subscription_id)

# Create an input Asset
print("Creating input asset " + in_asset_name)
# From SDK
# create_or_update(resource_group_name, account_name, asset_name, parameters, custom_headers=None, raw=False, **operation_config)
inputAsset = client.assets.create_or_update(resource_group_name, account_name, in_asset_name, input_asset)

# An AMS asset is a container with a specific id that has "asset-" prepended to the GUID.
# So, you need to create the asset id to identify it as the container
# where Storage is to upload the video (as a block blob)
in_container = 'asset-' + inputAsset.asset_id
in_container

# create an output Asset
print("Creating output asset " + out_asset_name)
# From SDK
# create_or_update(resource_group_name, account_name, asset_name, parameters, custom_headers=None, raw=False, **operation_config)
outputAsset = client.assets.create_or_update(resource_group_name, account_name, out_asset_name, output_asset)

### Use the Storage SDK to upload the video ###
print("Uploading the file " + source_file_name)

blob_service_client = BlobServiceClient.from_connection_string(storage_account_connection)

# From SDK
# get_blob_client(container, blob, snapshot=None)
blob_client = blob_service_client.get_blob_client(in_container,source_file_name)
working_dir = os.getcwd()
print("Current working directory:" + working_dir)
upload_file_path = os.path.join(working_dir, source_file_directory, source_file_name)

# WARNING: Depending on where you are launching the sample from, the path here could be off, and not include the BasicEncoding folder. 
# Adjust the path as needed depending on how you are launching this python sample file. 

# Upload the video to storage as a block blob
with open(upload_file_path, "rb") as data:
  # From SDK
  # upload_blob(data, blob_type=<BlobType.BlockBlob: 'BlockBlob'>, length=None, metadata=None, **kwargs)
    blob_client.upload_blob(data)

### Create a Transform ###
transform_name='ConvertToAAC'
# From SDK
# TransformOutput(*, preset, on_error=None, relative_priority=None, **kwargs) -> None
transform_output = TransformOutput(
    preset=BuiltInStandardEncoderPreset(preset_name="AACGoodQualityAudio")
)

transform = Transform()
transform.outputs = [transform_output]

print("Creating transform " + transform_name)
# From SDK
# Create_or_update(resource_group_name, account_name, transform_name, outputs, description=None, custom_headers=None, raw=False, **operation_config)
transform = client.transforms.create_or_update(
  resource_group_name=resource_group_name,
  account_name=account_name,
  transform_name=transform_name,
  parameters = transform
)

### Create a Job ###
job_name = 'Converting the MP3'+ str(uniqueness)
print("Creating job " + job_name)
files = (source_file_name)
# From SDK
# JobInputAsset(*, asset_name: str, label: str = None, files=None, **kwargs) -> None
input = JobInputAsset(asset_name=in_asset_name)
# From SDK
# JobOutputAsset(*, asset_name: str, **kwargs) -> None
outputs = JobOutputAsset(asset_name=out_asset_name)
# From SDK
# Job(*, input, outputs, description: str = None, priority=None, correlation_data=None, **kwargs) -> None
theJob = Job(input=input,outputs=[outputs])
# From SDK
# Create(resource_group_name, account_name, transform_name, job_name, parameters, custom_headers=None, raw=False, **operation_config)
job: Job = client.jobs.create(resource_group_name,account_name,transform_name,job_name,parameters=theJob)

### Check the progress of the job ### 
# From SDK
# get(resource_group_name, account_name, transform_name, job_name, custom_headers=None, raw=False, **operation_config)
job_state = client.jobs.get(resource_group_name,account_name,transform_name,job_name)
# First check
print("First job check")
print(job_state.state)

# Check the state of the job every 10 seconds. Adjust time_in_seconds = <how often you want to check for job state>
def countdown(t):
    while t: 
        mins, secs = divmod(t, 60) 
        timer = '{:02d}:{:02d}'.format(mins, secs) 
        print(timer, end="\r") 
        time.sleep(1) 
        t -= 1
    job_current = client.jobs.get(resource_group_name,account_name,transform_name,job_name)
    if(job_current.state == "Finished"):
      print(job_current.state)
      # TODO: Download the output file using blob storage SDK
      return
    if(job_current.state == "Error"):
      print(job_current.state)
      # TODO: Provide Error details from Job through API
      return
    else:
      print(job_current.state)
      countdown(int(time_in_seconds))

time_in_seconds = 10
countdown(int(time_in_seconds))

outputAsset.asset_id