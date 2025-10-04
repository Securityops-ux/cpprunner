import os
import subprocess
import uuid
import resource
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidSignatureError, InvalidTokenError
from typing import List
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

origins = [
    "*"  # For testing: allow all origins. In production, use specific domains.
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # GET, POST, PUT, DELETE, etc.
    allow_headers=["*"],  # Allow custom headers like CPP_TOKEN
)

ALGORITHM = "HS256"

def validate_token(token: str):
    CPP_KEY = os.getenv("CPP_KEY")
    print(CPP_KEY)
    try:
        decoded = jwt.decode(token, CPP_KEY, algorithms=[ALGORITHM])
        return decoded
    except ExpiredSignatureError:
        print(token)
        raise HTTPException(status_code=403, detail="Token Expired")
    except (InvalidSignatureError, InvalidTokenError):
        print(token)
        raise HTTPException(status_code=401, detail="Invalid Token")

class CppModel(BaseModel):
    code: str
    inputs: List[str] = []

def limit_resources():
    # CPU time limit (seconds)
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    # Memory limit (bytes)
    mem_limit = 100 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))

def run_sandboxed(exe_file, inp):
    try:
        run_proc = subprocess.run(
            [exe_file],
            input=inp,
            capture_output=True,
            text=True,
            timeout=5,
            cwd="/tmp",
            env={"PATH": "/usr/bin:/bin"},
            preexec_fn=limit_resources
        )
        return {"stdout": run_proc.stdout, "stderr": run_proc.stderr, "timeout": False}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "", "timeout": True}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "timeout": False}

@app.post("/run_cpp")
async def execute_cpp(data: CppModel, cpp_token: str = Header(..., alias="CPP_TOKEN")):
    validate_token(cpp_token)

    run_id = str(uuid.uuid4())
    cpp_file = f"/tmp/{run_id}.cpp"
    exe_file = f"/tmp/{run_id}.out"

    with open(cpp_file, "w") as f:
        f.write(data.code)

    # Compile once
    compile_proc = subprocess.run(
        ["g++", cpp_file, "-o", exe_file],
        capture_output=True,
        text=True
    )

    compile_result = {
        "success": compile_proc.returncode == 0,
        "stdout": compile_proc.stdout,
        "stderr": compile_proc.stderr
    }

    results = []

    if compile_result["success"]:
        # Run once per input
        for inp in data.inputs:
            exec_result = run_sandboxed(exe_file, inp)
            exec_result["input"] = inp
            results.append(exec_result)

    # Cleanup
    os.remove(cpp_file)
    if os.path.exists(exe_file):
        os.remove(exe_file)

    return {
        "compile": compile_result,
        "runs": results
    }


