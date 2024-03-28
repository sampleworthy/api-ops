from subprocess import Popen, PIPE
import requests
import time
import re
import os
import sys
import multiprocessing as mp
 
 
#ENV VARS set from the pipeline
clientId = os.getenv('clientId')
clientSecret = os.getenv('clientSecret')
resourceGroupName = os.getenv('resourceGroupName')
apimServiceName = os.getenv('apimServiceName')
tenantId = os.getenv('tenantId')
subscriptionId = os.getenv('subscriptionId')
resource = "https://management.azure.com/.default"
azureApiVersion = "2021-08-01"
baseUrl = f"https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.ApiManagement/service/{apimServiceName}"
 
results = {}
 
 
def getSession():
    return requests.Session()
 
 
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
 
 
def checkVersionSet(apiPath):
    #chill for sec
    time.sleep(1)
 
    token = getToken()
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
 
 
def createOrUpdateVersionSet(apiPath):
    token = getToken()
 
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
        return r.status_code
 
 
def createOrUpdateAPI(q, s, apiId, apiVersion, apiVersionSetId, apiPath, apiSpecPath, results):
    token = getToken()
 
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
        j = f"{apiId}: {r.status_code}"
        q.put(j)
        print(f"{r.status_code} {apiId}")
        return None
    elif r.status_code == 202:
        try:
            statusURL = r.headers['Azure-AsyncOperation']
            checkAsyncStatus(q, token, statusURL, apiId, results)
        except KeyError:
            statusURL = r.headers['Location']
            checkAsyncStatus(q, token, statusURL, apiId, results)
        return None
    elif r.status_code == 409:
        j = f"{apiId}: {r.status_code}"
        q.put(j)
        print(f"{r.status_code} {apiId} failed to load")
        print(r.text)
        return None
    elif r.status_code in (502, 504):
        j = f"{apiId}: {r.status_code}"
        q.put(j)
        print(f"{r.status_code} {apiId} failed to load")
        print(r.text)
        return None 
    else:
        j = f"{apiId}: {r.text}"
        q.put(j)
        print(f"{r.status_code} {apiId} failed to load")
        print(r.text)
        return None
 
 
def checkAsyncStatus(q, token, location, apiId, results):
    headers = {
        'Authorization': 'Bearer ' + token
    }
 
    while True:
        r = requests.get(location, headers=headers)
 
        if r.status_code == 202:
            print(f"{r.status_code} {apiId}")
            time.sleep(30)
        elif r.status_code in (200, 201):
            j = f"{apiId}: {r.status_code}"
            q.put(j)
            print(f"{r.status_code} {apiId}")
            break
        elif r.status_code in (502, 504):
            j = f"{apiId}: {r.status_code}"
            q.put(j)
            print(f"{r.status_code} {apiId} failed to load")
            print(r.text)
            break
        else:
            j = f"{apiId}: {r.text}"
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
 
 
def main():
 
    #token = getToken()
    s = getSession()
 
    regex = re.compile("^([a-zA-Z0-9_]*)-(v\d{0,3})\.yaml$")
    files = os.listdir('./openapi/')
    files = [file for file in files if regex.match(file)]
    if files:
        # Manager and Queue for worker procs
        manager = mp.Manager()
        q = manager.Queue()
        pool = mp.Pool(3, maxtasksperchild=1)
        watcher = pool.apply_async(listener, (q, ))
 
        print("Checking Version Sets...")
 
        vSets = []
        for file in files:
            x = re.split('-|\.', file)
            vSets.append(x[0])
        vSets = set(vSets)
        for vSet in vSets:
            check = checkVersionSet(vSet)
            if not check:
                print(f"Creating Version Set {vSet}")
                createOrUpdateVersionSet(vSet)
 
        print("Loading all spec files...")
 
        procs = []
        for file in files:
            x = re.split('-|\.', file)
            apiId = f"{x[0]}-{x[1]}"
            apiVersion = x[1]
            apiPath = x[0]
            apiVersionSetId = f"{baseUrl}/apiVersionSets/{apiPath}"
            apiSpecPath = 'apis/' + file
            proc = pool.apply_async(createOrUpdateAPI, args=(q, s, apiId,
                                                             apiVersion, apiVersionSetId, apiPath, apiSpecPath, results))
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