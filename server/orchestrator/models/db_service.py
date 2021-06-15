
from .base import Session, engine, Base
from .runtime_program_model import RuntimeProgram
from .message_model import Message
from sqlalchemy.orm import load_only
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class DBService():
    def __init__(self):
        Base.metadata.create_all(engine)

    def save_message(self, job_id, data):
        message = Message()
        message.job_id = job_id
        message.data = data
        message.creation_date = datetime.now()
        session = Session()
        try:
            session.add(message)
            session.commit()
        finally:
            session.close()

    def save_runtime_program(self, runtime_program: RuntimeProgram):
        session = Session()
        try:
            session.add(runtime_program)
            session.commit()
        finally:
            session.close()
    
    def fetch_runtime_program_data(self, program_id):
        try:
            session = Session()
            fields = ['data']
            program = session.query(RuntimeProgram).filter_by(program_id=program_id).options(load_only(*fields)).one()
            return program.data
        finally:
            session.close()

    def fetch_runtime_programs(self):
        result = []
        # programs = RuntimeProgram.query.all()
        try:
            session = Session()
            fields = ['program_id', 'name', 'program_metadata']
            programs = session.query(RuntimeProgram).options(load_only(*fields)).all()
            logger.debug(f"Found {len(programs)} programs")
            for program in programs:
                result.append({
                    'program_id': program.program_id,
                    'name': program.name,
                    'program_metadata': program.program_metadata
                })
            return result
        finally:
            session.close()


