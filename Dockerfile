# 1. A lightweight version of Python
FROM python:3.11-slim

# 2. Setting the working directory inside the container
WORKDIR /code

# 3. Copying the requirements file and installing the libraries
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt

# 4. Copying EVERYTHING into the container (This is the magic fix!)
# The first dot means "everything in my current computer folder"
# The second dot means "put it in the current container folder (/code)"
COPY . .

# 5. The command to start the server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]