@echo off
echo Installing Visual Studio Build Tools...
echo Please wait while we download and install the necessary build tools...
curl -L "https://aka.ms/vs/17/release/vs_buildtools.exe" --output vs_buildtools.exe
vs_buildtools.exe --quiet --wait --norestart --nocache --installPath "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools" --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.Windows10SDK

echo Creating virtual environment...
python -m venv venv311
call .\venv311\Scripts\activate

echo Upgrading pip...
python -m pip install --upgrade pip

echo Installing dependencies...
pip install --only-binary :all: numpy==1.24.3
pip install --only-binary :all: Pillow==10.2.0
pip install --only-binary :all: pandas==2.2.0
pip install --only-binary :all: PyQt5==5.15.10
pip install --only-binary :all: google-generativeai==0.3.2
pip install --only-binary :all: ffmpeg-python==0.2.0
pip install --only-binary :all: opencv-python==4.9.0.80

echo Setup complete!
echo Running the application...
python metadata_app.py

pause 