#!/usr/bin/python

import subprocess
import re
import shlex
import os
import sys
import tempfile
import argparse
import json
import logging as log
import asyncio

from enum import Enum


CONFIG = {
	"presets": {
		"default": {
			"output": "{base}_desilenced.mkv",
			"silencedetect": "ffmpeg -hide_banner -nostdin -i {input} -af silencedetect=n=-50dB:d=0.5 -vn -f null -",
			"segment_encoder": "ffmpeg -hide_banner -nostdin -ss {start} -i {input} {duration} -c:v libx264 -crf 26 -preset slow -c:a libopus -b:a 96k -y {output}"
		}
	}
}

class SegmentType(Enum):
	AUDIBLE = 1,
	INAUDIBLE = 2

def format_array(arr, **kwargs):
	_arr = []
	for x in arr:
		_arr.append(x.format(**kwargs))
	return _arr

def parse_silencedetect(output):
	'''Parses unstable ffmpeg output into segments of silence'''
	last_start = 0.0
	last_end = 0.0
	total_duration = 0.0

	segments = []
	
	# we need to convert silence segments into the inverse: audible sections
	for line in output.splitlines():
		m = re.match(r'^\[silencedetect[^]]+\] (.+)$', line)
		if m is not None:
			data = m.group(1)
			
			if data.startswith("silence_start"):
			
				data = re.match(r'^silence_start: ([e0-9.-]+)$', data)
				last_start = float(data.group(1))
				segments.append((SegmentType.AUDIBLE, last_end, last_start))
				
				# entering silence, clear last_end
				last_end = 0.0

			elif data.startswith("silence_end"):
				data = re.match(r'^silence_end: ([e0-9.-]+) \| silence_duration: ([0-9.]+)$', data)
				
				last_end = float(data.group(1))
				segments.append((SegmentType.INAUDIBLE, last_start, last_end))
				
				total_duration += float(data.group(2))

				# left silence, clear last_start
				last_start = 0.0
			else:
				raise Exception("Unkown formating from silencedetect filter, please report this error. Line " + data)
	
	# if we end in audible segment, we are missing the last segment
	if last_end > 0.0:
		log.debug("last segment is audible, manually adding segment")
		segments.append((SegmentType.AUDIBLE, last_end, None))
	
	return (segments, total_duration)


log.basicConfig(level=log.DEBUG)
parser = argparse.ArgumentParser(description = "Removes silence from (lecture) records", allow_abbrev = False)
parser.add_argument("--input", "-i", help = "specifies input file", required = True)
parser.add_argument("--output", "-o", help = "specifies output file (supports {base} and {ext} substitution)")
parser.add_argument("--config", "-c", help = "path to config")
parser.add_argument("--preset", "-p", help = "selects encoder string with given name in config")
parser.add_argument("--parallel", "-j", help = "number of parallel ffmpeg instances (defaults to logical core count) [not yet implemented]", type = int)
parser.add_argument("--verbose", "-v", help = "increase verbosity", action = "store_true")

args = parser.parse_args()

if args.verbose:
	log.getLogger().setLevel(log.DEBUG)

if not os.path.isfile(args.input):
	log.error("file not found: " + args.input)
	sys.exit(-1)
input = args.input

if args.config is not None:
	with open(args.config) as file:
		log.info("loaded additional presets from " + args.config)
		data = json.load(file)
		CONFIG["presets"] |= data["presets"]

preset = args.preset or "default"
if preset not in CONFIG["presets"]:
	log.error("unable to find preset: " + preset)
	log.info("available presets: " + ", ".join(CONFIG["presets"].keys()))
	sys.exit(-1)
log.info("using preset " + preset)
preset = CONFIG["presets"][preset]

output = args.output or preset["output"]
input_filename = os.path.basename(args.input)
(base, ext) = os.path.splitext(input_filename)
output = output.format(base = base, ext = ext)

if os.path.exists(output):
	log.error("Ouput file already exists: " + output)
	sys.exit(-1)

log.info("detecting silence segments... this may take a few seconds")
format_array(shlex.split(preset["silencedetect"]), input = input)
silencedetect = subprocess.run(format_array(shlex.split(preset["silencedetect"]), input = input), text = True, capture_output = True)
if silencedetect.returncode != 0:
	log.error("silencedetect exited with non-zero return code: \n" + silencedetect.stderr)
	sys.exit(-1)

# parse ffmpeg output
(segments, total_duration) = parse_silencedetect(silencedetect.stderr)
log.info("Found total of " + str(len(segments)) + " segments with total duration of " + str(total_duration) + " seconds of silence.")

if log.getLogger().getEffectiveLevel() == log.DEBUG:
	for (type, start, end) in segments:
		log.debug("segment: " + str(type) + " from " + str(start) + " to " + (str(end) if end is not None else "end"))

# start processing in temporary directory
# create temporary directory for processing of segments
with tempfile.TemporaryDirectory() as dir:
	log.info("Extracting segments in temporary directory " + dir + "...")
	concat = ""
	i = 0

	for (type, start, end) in segments:
		# duration is None for last segment, in which case we omit the -t parameter
		if end is not None:
			duration = end - start
		else:
			duration = None
		
		if type == SegmentType.AUDIBLE and (duration is None or duration > 0.0):
			log.info("processing segment " + str(i) + "/" + str(len(segments)))
			seg_file = os.path.join(dir, "seg_" + str(i) + ".nut")
		
			# since -t argument requires two arguments, we need to inject the placeholder before splitting the strings
			preset_command = preset["segment_encoder"]
			if duration is None:
				# remove placeholder if duration is None
				preset_command = preset_command.replace("{duration}", "")
			else:
				# replace placeholder with -t argument and let split handle the rest
				preset_command = preset_command.replace("{duration}", "-t {duration}")

			# TODO: multi threaded
			segment_encoder = subprocess.run(format_array(shlex.split(preset_command),
					input = input,
					output = seg_file,
					start = start,
					duration = "{:.4f}".format(duration) if duration is not None else ""
			), text = True, capture_output = True)
			if segment_encoder.returncode != 0:
				log.error("error encoding segment " + str(i) + " at " + str(start) + "seconds: " + segment_encoder.stderr)
				sys.exit(-1)
			
			# sometimes segments are corrupt and contain no audio, we use ffpb to detect this
			ffprobe_test = subprocess.run([
				"ffprobe",
				"-hide_banner",
				"-count_frames",
				"-loglevel",
				"error",
				"-print_format",
				"json",
				"-show_streams",
				seg_file
			], text = True, capture_output = True)
			if ffprobe_test.returncode != 0:
				log.warning("skipping segment " + str(i) + " because it is corrupt")
				continue
			stream_json = json.loads(ffprobe_test.stdout)

			# despite no errors, some segments are too short to contain any frames
			# we skip these as well by requesting the frame count from ffprobe and cheking for "N/A"
			# both video and audio can be N/A and we check for both and report them individually
			all_streams_fine = True
			for stream in stream_json["streams"]:
				human_readable_idenfier = f'stream {stream["index"]}: {stream["codec_type"]} ({stream["codec_name"]})'

				if not "nb_read_frames" in stream or stream["nb_read_frames"].lower() == "n/a":
					log.warning("skipping segment " + str(i) + " because " + human_readable_idenfier + " has no frames")
					all_streams_fine = False
			
			if not all_streams_fine:
				continue

			# only append if there were no errors
			concat += "file '" + seg_file + "'\n"

		# counting audible segments is important to display accurate progress
		i += 1

	concat_file = os.path.join(dir, "concat.txt")
	print(concat, file = open(concat_file, "w"))
	log.info("Reassemble segments...")
	subprocess.check_output([
		"ffmpeg",
		"-fflags",
		"+genpts",
		"-hide_banner",
		"-nostdin",
		"-f",
		"concat",
		"-safe",
		"0",
		"-i",
		concat_file,
		"-c",
		"copy",
		output
	])
	log.info("removed " + str(total_duration) + " precious seconds of nothingness in " + output)
