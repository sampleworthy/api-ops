# api-ops
This workflow will:

1. Check out your code.
2. Log in to Azure.
3. Loop over all YAML files in the apis directory.
4. For each file, it will check if an API with the same name as the file (minus the extension) exists in the APIM instance.
5. If the API does not exist, it will create a new one.
6. If the API does exist, it will create a new revision and import the OpenAPI spec into that revision.
