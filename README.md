## A2E-Transcriber
### An "Anything To English" audio transcription interface created with AI.

Transcription queue and archive of transcribed files
<img width="492" alt="image" src="https://github.com/user-attachments/assets/500cd4ac-3538-45c7-a442-d114b260fb0e" />

Transcription details
<img width="492" alt="image" src="https://github.com/user-attachments/assets/c7dc153e-877c-4af2-8a87-13ea5f89f359" />


> [!WARNING]
> ### THIS CODE WAS MOSTLY WRITTEN BY AI WITH MY GUIDANCE.
> ### I AM NOT A PYTHON DEVELOPER BUT HAVE A FEW DECADES UNDER MY BELT WITH PHP
> ### I CANNOT GUARANTEE THE VALIDITY OR SANITY OF THIS CODE (ALTHOUGH IT LOOKS/RUNS ALRIGHT TO ME) ;)
> ### DO NOT RUN THIS ON A PUBLIC FACING SERVER! THIS WAS NOT DEVELOPED WITH SECURITY IN MIND. YOU HAVE BEEN WARNED!

Built with Python and requires Whisper.cpp to be compiled and sitting in a directory directly next to the transcriber directory.

Note! This will run on a Raspberry PI 4 8GB but is extremely slow when using the "small" or "medium" Whisper models.
The faster your machine is (especially the GPU) the faster the translation will happen.
This code could also be altered to run the larger (smarter) models on a faster machine.

Only tested on Linux (Mint 22, Debian Trixie)

### REQUIRED DIRECTORY STRUCTURE

```
BASE_DIR
          |
		  -- A2E-Transcriber
		  |
		  -- whisper.cpp
```
### Install required packages

```
sudo apt install python3 python3-flask python3-flask-sqlalchemy python3-flask-login ffmpeg cmake git
```
### Clone the whisper.cpp project and compile it.
### whisper.cpp AND A2E-Transcriber MUST be cloned within the same directory

```
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp
make
```
### Download whisper models
This next block of commands should be done in the whisper.cpp/models directory

```
cd models
./download-ggml-model.sh tiny
./download-ggml-model.sh small
./download-ggml-model.sh base
./download-ggml-model.sh medium
```
### Download the transcriber repository

```
cd ../../
git clone https://github.com/ILL-DIE-TRYING/A2E-Transcriber
```

## Prepare the transcriber for first start and user generation

### Enable user registration in config.py, register your user, and then IMMEDIATLY disable user registration (IMPORTANT!)

```
cd A2E-Transcriber
nano config.py
```

Change the following line to "True" and save the file

`REGISTRATION_ENABLED = False`

## --- Authentication Configuration ---
Set to True to enable the /register route for initial user creation.
Set to False (SECURE DEFAULT) immediately after the first user is created.

`REGISTRATION_ENABLED = True`

### DO NOT LEAVE THIS SET TO TRUE!! YOU WILL REGRET IT!

### Manually fire up the transcriber to test and save the initial user.

`python3 app.py`

The transcriber should start up and tell you the url to view the web interface.
At this point you should be able to browse to the transciber URL with your web browser.
I suggest bookmarking the url. You should be presented with a login box that has an option to register an account. 
Choose register, fill in the form, and when finished, save and try logging in.

### ONCE YOU HAVE LOGGED IN YOU SHOULD EDIT config.py and set REGISTRATION_ENABLED to "False".

```
nano config.py
```

### --- Authentication Configuration ---
Set "REGISTRATION_ENABLED" to True to enable the /register route for initial user creation.
Set "REGISTRATION_ENABLED" to False (SECURE DEFAULT) immediately after the first user is created.
### DO NOT LEAVE THIS SET TO TRUE!! IT IS A SECURITY RISK!

`REGISTRATION_ENABLED = False`

### Manually start the transcriber and make sure it starts okay.
Once it starts, I suggest browsing to it again, logging in, and testing out a file before creating a systemd service for it to run automatically.

### OPTIONAL Set up a systemd service to run the transcriber.
To run the transcriber as a service. Change the user to the user you plan to use to run the service:
create the service file:

`sudo nano /etc/systemd/system/transcriber.service`

### Paste this to the service file (BE SURE TO CHANGE THE PATH TO THE FILES AND THE USER!!):

```
[Unit]
Description=Local Audio Tanscriber
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/A2E-Transcriber/app.py
WorkingDirectory=/home/pi/A2E-Transcriber
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

### Enable the service, start it, and check if it started okay:

```
sudo systemctl enable transcriber
sudo systemctl start transcriber
sudo systemctl status transcriber
```

