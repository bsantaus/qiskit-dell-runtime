import os
import flask
from flask import Flask, Response
import logging
import json
from logging.config import fileConfig
from qiskit.providers.ibmq.runtime.utils import RuntimeEncoder
from qiskit_emulator import EmulatorProvider

app = Flask(__name__)
import uuid
from datetime import datetime

from .kube_client import KubeClient
from .models import DBService, RuntimeProgram, Job

emulator_provider = EmulatorProvider()

db_service = DBService()
kube_client = KubeClient()

ACTIVE="Active"
INACTIVE="Inactive"
CREATING="Creating"
RUNNING = "Running"
COMPLETED = "Completed"
FAILED = "Failed"
CANCELED = "Canceled"

path = '/'.join((os.path.abspath(__file__).replace('\\', '/')).split('/')[:-1])
fileConfig(os.path.join(path, 'logging_config.ini'))
logger = logging.getLogger(__name__)

def random_id():
    new_uuid = uuid.uuid4()
    return str(new_uuid)[-12:]

@app.route('/program', methods=['POST'])
def upload_runtime_program():
    json_data = flask.request.json
    
    program = RuntimeProgram()
    new_id = random_id()
    program.program_id = new_id
    program.name = json_data["name"] if json_data["name"] else new_id
    program.program_metadata = json.dumps(json_data['program_metadata'])
    program.data = bytes(json_data['data'], 'utf-8')
    program.status = ACTIVE
    db_service.save_runtime_program(program)
    return (new_id, 200)

@app.route('/program/<program_id>/update', methods=['POST'])
def update_runtime_program(program_id):
    json_data = flask.request.json
    
    name = None
    data = None
    program_metadata = None
    if json_data['name']:
        name = json_data['name']
    if json_data['data']:
        data = bytes(json_data['data'], 'utf-8')
    if json_data['program_metadata']:
        program_metadata = json_data['program_metadata']
    
    db_service.update_runtime_program(program_id, name, data, program_metadata)
    return ("", 200)

@app.route('/program', methods=['GET'])
def programs():
    result = db_service.fetch_runtime_programs()
    logger.debug(f"GET /program: {result}")
    json_result = json.dumps(result)
    return Response(json_result, status=200, mimetype="application/json")

# this URL needs to be a lot more restrictive in terms of security
# 1. only available to internal call from other container
# 2. only allow fetch of data of assigned program
@app.route('/program/<program_id>/data', methods=['GET'])
def program_data(program_id):
    result = db_service.fetch_runtime_program_data(program_id)
    return Response(result, 200, mimetype="application/binary")

@app.route('/program/<program_id>/delete', methods=['GET'])
def delete_program(program_id):
    db_service.delete_runtime_program(program_id)
    return Response(None, 200, mimetype="application/binary")

@app.route('/status', methods=['GET'])
def get_status():
    json_result = json.dumps(False)
    return Response(json_result, 200, mimetype="application/json")

@app.route('/backends', methods=['GET'])
def get_backends():
    backends = emulator_provider.runtime.backends()
    result = []
    for backend in backends:
        backend_config = backend.configuration()
        result.append({
            'name': backend_config.backend_name,
            'backend_name': backend_config.backend_name,
            'description': backend_config.description,
            'n_qubits': backend_config.n_qubits,
            'basis_gates': backend_config.basis_gates
        })
    json_result = json.dumps(result)
    return Response(json_result, 200, mimetype="application/json")

@app.route('/program/<program_id>/job', methods=['POST'])
def run_program(program_id):
    inputs_str = flask.request.json

    job_id = random_id()
    pod_name = "qre-" + str(uuid.uuid1())[-24:]    
    options = {
        "program_id": program_id,
        "inputs_str": inputs_str,
        "job_id": job_id,
        "pod_name": pod_name
    }

    db_job = Job()
    db_job.job_id = job_id
    db_job.status = CREATING
    db_job.pod_name = pod_name
    db_service.save_job(db_job)

    kube_client.run(**options)
    # create job and return later
    return Response(job_id, 200, mimetype="application/json")

@app.route('/job/<job_id>/status', methods=['GET'])
def get_job_status(job_id):
    try:
        logger.debug(f'GET /job/{job_id}/status')
        result = db_service.fetch_job_status(job_id)
        return Response(result, 200, mimetype="application/binary")
    except:
        return Response("", 204, mimetype="application/binary")

@app.route('/job/<job_id>/status', methods=['POST'])
def update_job_status(job_id):
    status = flask.request.json
    logger.debug(f"GET /job/{job_id}/status: {status}")

    db_service.update_job_status(job_id, status)
    return ("", 200)

@app.route('/job/<job_id>/cancel', methods=['GET'])
def cancel_job(job_id):
    status = db_service.fetch_job_status(job_id)
    logger.debug(f"GET /job/{job_id}/cancel")
    if status == COMPLETED or status == FAILED or status == CANCELED:
        return ("Job no longer running", 204)
    else:
        try:
            pod_name = db_service.fetch_pod_name(job_id)
            kube_client.cancel(pod_name)
            db_service.update_job_status(job_id, CANCELED)
            return ("", 200)
        except:
            return ("Job no longer running", 204)

# TODO check for runtime to make sure only executor 
# for this specific job can call this URL 
@app.route('/job/<job_id>/message', methods=['POST'])
def add_message(job_id):
    data = flask.request.data
    db_service.save_message(job_id, data)
    return ("", 200)

# TODO determine whether kubernetes pod is launched


@app.route('/job/<job_id>/results', methods=['GET'])
def get_job_results(job_id):
    try:
        logger.debug(f"GET /job/{job_id}/results")
        result = db_service.fetch_messages(job_id, None)
        return Response(json.dumps({"messages": result}), 200, mimetype="application/binary")
    except:
        return Response(json.dumps({"messages": []}), 204, mimetype="application/binary")

@app.route('/job/<job_id>/results/<timestamp>', methods=['GET'])
def get_new_job_results(job_id, timestamp):
    try:
        logger.debug(f"GET /job/{job_id}/results/{timestamp}")
        tstamp = datetime.fromisoformat(timestamp)
        result = db_service.fetch_messages(job_id, tstamp)
        return Response(json.dumps({"messages": result}), 200, mimetype="application/binary")
    except:
        return Response(json.dumps({"messages": []}), 204, mimetype="application/binary")

@app.route('/job/<job_id>/delete_message', methods=['GET'])
def delete_message(job_id):
    db_service.delete_message(job_id)
    return Response(None, 200)
