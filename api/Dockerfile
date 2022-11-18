FROM python:3.7
ADD . /api
WORKDIR /api
# RUN apt-get update && apt-get install -y libldap2-dev
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
EXPOSE 8000
CMD ["gunicorn", "-w 3", "-b", "0.0.0.0:8000", "birdsong_responder:app"]
