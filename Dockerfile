# 1. Start with a lightweight version of Python
FROM python:3.11-slim

# 2. Set the working directory inside the container
WORKDIR /code

# 3. Copy your requirements file and install the libraries (FastAPI, Pandas, etc.)
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt

# 4. Copy your actual Python code into the container
COPY ./app /code/app

# 5. The command to start your server (Google Cloud Run expects port 8080)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
