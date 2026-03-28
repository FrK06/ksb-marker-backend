import os
from dotenv import load_dotenv
from google.cloud import discoveryengine_v1 as discoveryengine
from google.api_core.client_options import ClientOptions

load_dotenv()

PROJECT_ID = "webrag-451411"
LOCATION = "eu"
COLLECTION = "default_collection"
DATA_STORE_ID = "kb-datastore"
BUCKET_URI = "gs://kb-chatbot-docs-webrag"

CLIENT_OPTIONS = ClientOptions(api_endpoint="eu-discoveryengine.googleapis.com")

def create_data_store():
    client = discoveryengine.DataStoreServiceClient(client_options=CLIENT_OPTIONS)
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/{COLLECTION}"

    data_store = discoveryengine.DataStore(
        display_name="kb-datastore",
        industry_vertical=discoveryengine.IndustryVertical.GENERIC,
        content_config=discoveryengine.DataStore.ContentConfig.CONTENT_REQUIRED,
    )

    operation = client.create_data_store(
        parent=parent,
        data_store=data_store,
        data_store_id=DATA_STORE_ID,
    )
    print("Creating data store... please wait")
    result = operation.result()
    print(f"Data store created: {result.name}")
    return result

def import_documents():
    client = discoveryengine.DocumentServiceClient(client_options=CLIENT_OPTIONS)
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/{COLLECTION}/dataStores/{DATA_STORE_ID}/branches/default_branch"

    request = discoveryengine.ImportDocumentsRequest(
        parent=parent,
        gcs_source=discoveryengine.GcsSource(
            input_uris=[f"{BUCKET_URI}/*"],
            data_schema="content",
        ),
        reconciliation_mode=discoveryengine.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL,
    )

    operation = client.import_documents(request=request)
    print("Importing documents... please wait")
    result = operation.result()
    print(f"Import complete: {result}")

if __name__ == "__main__":
    import_documents()