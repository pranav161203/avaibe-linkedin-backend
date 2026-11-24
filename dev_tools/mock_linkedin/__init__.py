"""Dummy LinkedIn data in the Community Management API's exact response format, and a local stand-in server.

Used to build and test the app's LinkedIn connection before real API access exists. Everything here is
synthetic: the formats follow LinkedIn's documentation (version 202611); the numbers are generated to behave
like a real company page (calibrated on an actual LinkedIn export) but belong to no real company or person.
"""

from pathlib import Path

# Generated data and the calibration file live next to manage.py, outside the code
MOCK_DIR = Path(__file__).resolve().parents[2] / "mock_data"
