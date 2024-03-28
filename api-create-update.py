from subprocess import CalledProcessError, getoutput
from os import listdir, getenv
from os.path import isfile, join
import tempfile
import requests
import time
import re
import sys
import json
import pathlib
import shutil
import traceback
import multiprocessing as mp



# ENV VARS come from the pipeline
clientId = getenv('clientId')
clientSecret = getenv('clientSecret')
resourceGroupName = getenv('resourceGroupName')
apimServiceName = getenv('apimServiceName')
tenantId = getenv('tenantId')
subscriptionId = getenv('subscriptionId')
resource = "https://management.azure.com/.default"
azureApiVersion = "2021-08-01"
baseUrl = f"https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.ApiManagement/service/{apimServiceName}"


def getSession():
    return requests.Session()

def createTempdir():
    return tempfile.TemporaryDirectory()

def getToken():
    url = f"https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token"
    data = {
        "client_id": clientId,
        "client_secret": clientSecret,
        "grant_type": "client_credentials",
        "scope": resource
    }
    r = requests.post(url, data=data)
    if r.status_code == 200:
        return r.json()['access_token']
    else:
        print(r.status_code)
        print(r.text)
        sys.exit(1)


def checkVersionSet(apiPath, token):
    # chill for sec
    time.sleep(1)
    url = f"{baseUrl}/apiVersionSets/{apiPath}"

    params = {
        'api-version': azureApiVersion
    }
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
        'If-Match': '*'
    }
    r = requests.get(url, params=params, headers=headers)
    if r.status_code == 200:
        return r.status_code
    else:
        return None


def createOrUpdateVersionSet(apiPath, token):
    url = f"{baseUrl}/apiVersionSets/{apiPath}"

    params = {
        'api-version': azureApiVersion
    }
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
        'If-Match': '*'
    }
    data = {
        'properties': {
            "displayName": apiPath,
            "versioningScheme": "Header",
            "versionHeaderName": "X-API-VERSION"
        }
    }

    r = requests.put(url=url, params=params, headers=headers, json=data)

    if r.status_code in (200, 201):
        print(f"{r.status_code} Created Version Set {apiPath}")
        return r.status_code
    else:
        print(f"{r.status_code} Error creating Version Set {apiPath}")
        print(r.text)
        return r.status_code


def createOrUpdateAPI(q, s, token, apiId, apiVersion, apiVersionSetId, apiPath, apiSpecPath):
    with open(apiSpecPath, 'r') as fd:
        openApiSpec = fd.read()

    url = f"{baseUrl}/apis/{apiId}"
    params = {
        'api-version': azureApiVersion
    }
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
        'If-Match': '*'
    }
    data = {
        "properties": {
            "apiVersion": apiVersion,
            "apiVersionSetId": apiVersionSetId,
            "path": apiPath,
            "format": "openapi",
            "value": openApiSpec
        }
    }

    request = requests.Request(
        'PUT', url, params=params, headers=headers, json=data)
    prepped = s.prepare_request(request)
    try:
        r = s.send(prepped)
    except Exception as e:
        print(e)
    if r.status_code in (200, 201):
        data = {}
        data[apiId] = r.status_code
        j = json.dumps(data)
        q.put(j)
        print(f"{r.status_code} {apiId}")
        return None
    elif r.status_code == 202:
        try:
            statusURL = r.headers['Azure-AsyncOperation']
            checkAsyncStatus(q, token, statusURL, apiId)
        except KeyError:
            statusURL = r.headers['Location']
            checkAsyncStatus(q, token, statusURL, apiId)
        return None
    elif r.status_code == 404:
        print(r.status_code)
        print(r.json())
    elif r.status_code == 409:
        data = {}
        data[apiId] = r.status_code
        j = json.dumps(data)
        q.put(j)
        print(f"{r.status_code} {apiId} will not retry")
        print(r.text)
        return None
    else:
        data = {}
        data[apiId] = r.status_code
        j = json.dumps(data)
        q.put(j)
        print(f"{r.status_code} {apiId} failed to load")
        print(r.text)
        return None


def checkAsyncStatus(q, token, location, apiId):
    headers = {
        'Authorization': 'Bearer ' + token
    }

    while True:
        r = requests.get(location, headers=headers)

        if r.status_code == 202:
            print(f"{r.status_code} {apiId}")
            time.sleep(30)
        elif r.status_code in (200, 201):
            data = {}
            data[apiId] = r.status_code
            j = json.dumps(data)
            q.put(j)
            print(f"{r.status_code} {apiId}")
            break
        elif r.status_code in (502, 504):
            data = {}
            data[apiId] = r.status_code
            j = json.dumps(data)
            q.put(j)
            print(f"{r.status_code} {apiId} failed to load")
            print(r.text)
            #500s mean the azure api is having trouble
        else:
            data = {}
            data[apiId] = r.status_code
            j = json.dumps(data)
            q.put(j)
            print(f"{r.status_code} {apiId}")
            print(r.text)
            break


def listener(q):
    with open('results.json', 'w') as f:
        while True:
            m = q.get()
            if m == 'kill':
                break
            f.write(str(m) + '\n')
            f.flush()


def renameFiles(commitId, tempDir):
    # Get list of files in the commit
    try:
        p = getoutput(
            f"git diff-tree --no-commit-id --name-only -r --diff-filter=d {commitId}^ {commitId}")
    except CalledProcessError as e:
        print(e)
    # Transform output to get a list of spec files from the commit
    files = p.split('\n')
    filename = 'openapi-resolved-apim.yaml'
    renamedFiles = []

    # Rename and return a list of files
    for file in files:
        if filename in file:
            p = pathlib.PurePath(file)
            n = p.parts[1] + '-' + p.parts[2]+'.yaml'
            try:
                shutil.copyfile(file, tempDir.name + '/' + n)
            except Exception:
                print(traceback.format_exc())
                sys.exit(1)
    renamedFiles = [f for f in listdir(
        tempDir.name) if isfile(join(tempDir.name, f))]

    return renamedFiles


def main():
    s = getSession()
    token = getToken()
    tempDir = createTempdir()

    # Commit ID needs to be passed as an arg
    commitId = sys.argv[1]

    # Get a list of absolute filenames to be deployed
    files = renameFiles(commitId, tempDir)

    print("Files to be deployed:")
    print(files)
    if files:
        # Manager and Queue for worker procs
        manager = mp.Manager()
        q = manager.Queue()
        # Number of workers to create
        pool = mp.Pool(4, maxtasksperchild=1)
        watcher = pool.apply_async(listener, (q, ))
        print("Checking Version Sets...")

        vSets = []
        for file in files:
            x = re.split('-|\.', file)
            vSets.append(x[0])
        vSets = set(vSets)
        for vSet in vSets:
            check = checkVersionSet(vSet, token)
            if not check:
                print(f"Creating Version Set {vSet}")
                createOrUpdateVersionSet(vSet, token)

        procs = []
        for file in files:
            x = re.split('-|\.', file)
            apiId = f"{x[0]}-{x[1]}"
            apiVersion = x[1]
            apiPath = x[0]
            apiVersionSetId = f"{baseUrl}/apiVersionSets/{apiPath}"
            apiSpecPath = tempDir.name + '/' + file
            proc = pool.apply_async(createOrUpdateAPI, args=(q, s, token, apiId,
                                                             apiVersion, apiVersionSetId, apiPath, apiSpecPath))
            procs.append(proc)
        for proc in procs:
            proc.get()
        q.put('kill')
        pool.close()
        pool.join()
    else:
        print("Didnt find any spec files, exiting")
        sys.exit(1)


if __name__ == "__main__":
    main()