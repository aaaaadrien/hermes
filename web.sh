#! /bin/bash
export TMPDIR=/var/tmp
source venv/bin/activate
python -m streamlit run hermes-web.py
deactivate
