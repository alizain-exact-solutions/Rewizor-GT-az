import requests

response = requests.get("http://rewizor-api.ngrok.dev/documents",
    headers={
      "Accept": "*/*",
      "x-api-key": "rida_PiL1FS2Dn5xMRlU9p6M24Y537tWTc2Su5ow3T8sQuVvNmccXVM7g4GCbS46iU2ANnChBB1MQwTYFO0FotmqxvfCCEnaXMoJzGLtOw001IIXv8rg3OTOc5YTEcj2BnLHC"
    }
)


print(response.json())