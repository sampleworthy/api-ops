# api-ops

The provided GitHub Actions workflow is set up to import APIs into Azure API Management (APIM). Here's a step-by-step breakdown of what it does:

It checks out your repository using the actions/checkout@v2 action.
It installs yq, a command-line YAML processor.
It logs into Azure using the azure/login@v1 action with your Azure credentials.
It loops over all the .yaml files in the ./apis/ directory. For each file:
It extracts the base name of the file (without the .yaml extension) and uses it as the API name.
It extracts the url from the servers[0] field in the YAML file and uses it as the service URL for the API.
It extracts the version from the info field in the YAML file and uses it as the API version.
It constructs a display name for the API by appending the version to the base name.
It imports the API into APIM using the az apim api import command with the extracted name, service URL, and version, and the constructed display name.
It gets an access token and the subscription ID from Azure.
It gets the API ID of the imported API from APIM.
It updates the apiVersion field of the imported API using a curl command to send a PATCH request to the APIM REST API.
