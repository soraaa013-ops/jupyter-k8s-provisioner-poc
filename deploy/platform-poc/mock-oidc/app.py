import base64
import os
import time
import uuid
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

app = FastAPI(title="Jupyter POC mock OIDC")
ISSUER = os.getenv("OIDC_ISSUER", "http://mock-oidc.jupyter-poc.svc:8080/jupyter")
CLIENT_ID = "jupyter-poc"
CLIENT_SECRET = os.environ["OIDC_CLIENT_SECRET"]
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
kid = uuid.uuid4().hex
codes = {}


def b64int(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@app.get("/isalive")
def alive():
    return {"status": "ok"}


@app.get("/jupyter/.well-known/openid-configuration")
def discovery():
    return {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token", "userinfo_endpoint": f"{ISSUER}/userinfo",
            "jwks_uri": f"{ISSUER}/jwks", "response_types_supported": ["code"],
            "subject_types_supported": ["public"], "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile", "groups"]}


@app.get("/jupyter/jwks")
def jwks():
    public = key.public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
                       "n": b64int(public.n), "e": b64int(public.e)}]}


@app.get("/jupyter/authorize")
def authorize(client_id: str, redirect_uri: str, state: str, response_type: str = "code", scope: str = "openid"):
    if client_id != CLIENT_ID or response_type != "code":
        raise HTTPException(400, "invalid OAuth request")
    code = uuid.uuid4().hex
    codes[code] = {"redirect_uri": redirect_uri, "scope": scope, "expires": time.time() + 60}
    return RedirectResponse(f"{redirect_uri}?{urlencode({'code': code, 'state': state})}", status_code=302)


@app.post("/jupyter/token")
def token(grant_type: str = Form(...), code: str = Form(...), client_id: str = Form(...),
          client_secret: str = Form(...), redirect_uri: str = Form(...)):
    grant = codes.pop(code, None)
    if (grant_type != "authorization_code" or client_id != CLIENT_ID or client_secret != CLIENT_SECRET
            or not grant or grant["expires"] < time.time() or grant["redirect_uri"] != redirect_uri):
        raise HTTPException(400, "invalid grant")
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": "poc-user", "preferred_username": "poc-user",
              "groups": ["jupyter-users"], "aud": CLIENT_ID, "iat": now, "exp": now + 300}
    encoded = jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})
    return {"access_token": encoded, "id_token": encoded, "token_type": "Bearer", "expires_in": 300}


@app.get("/jupyter/userinfo")
def userinfo(request: Request):
    value = request.headers.get("authorization", "")
    if not value.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        claims = jwt.decode(value[7:], key.public_key(), algorithms=["RS256"], audience=CLIENT_ID, issuer=ISSUER)
    except Exception:
        raise HTTPException(401, "invalid token")
    return {"sub": claims["sub"], "preferred_username": claims["preferred_username"], "groups": claims["groups"]}
