# KYUGen V1 - Metadata Generator

A modern PyQt5-based application for generating metadata for files using a simulated API interface.

## Features

- Modern, dark-themed GUI with custom title bar
- API key management with visibility toggle
- Model selection
- Configurable processing parameters
- Multi-threaded file processing
- Progress tracking
- Configuration persistence
- Directory selection for input/output

## Requirements

- Python 3.6+
- PyQt5

## Installation

1. Clone this repository
2. Install the requirements:
```bash
pip install -r requirements.txt
```

## Usage

1. Run the application:
```bash
python metadata_app.py
```

2. Configure the settings:
   - Enter your API key
   - Select the model
   - Choose input/output directories
   - Adjust processing parameters

3. Click "Start" to begin processing
   - Progress will be shown in real-time
   - Use "Stop" to interrupt processing

4. Settings are automatically saved between sessions

## Configuration

The application saves its configuration in `config.json`. This includes:
- API key
- Selected model
- Input/output paths
- Processing parameters

## Note

This is a simulation application and does not actually process files. It's designed to demonstrate the UI and workflow of a metadata generation tool. 