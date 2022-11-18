FROM python:3.7
ADD . /api
RUN pip install --upgrade pip
RUN pip install -r api/requirements.txt
EXPOSE 8000
CMD ["gunicorn", "-w 3", "-b", "0.0.0.0:8000", "birdsong_responder:app"]
