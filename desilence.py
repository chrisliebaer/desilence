#!/usr/bin/python

import subprocess
import re
import shlex
import os
import sys
import tempfile
import math
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
			"segment_encoder": "ffmpeg -hide_banner -nostdin -ss {start} -i {input} -t {duration} -c:v libx264 -crf 26 -preset slow -c:a libopus -b:a 96k -y {output}"
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
				data = re.match(r'^silence_start: ([0-9.]+)$', data)
				
				last_start = float(data.group(1))
				segments.append((SegmentType.AUDIBLE, last_end, last_start))
				
			elif data.startswith("silence_end"):
				data = re.match(r'^silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)$', data)
				
				last_end = float(data.group(1))
				segments.append((SegmentType.INAUDIBLE, last_start, last_end))
				
				total_duration += float(data.group(2))
			else:
				raise Exception("Unkown formating from silencedetect filter, please report this error. Line " + data)
	
	
	# TODO: make sure last segment is handled correctly in all cases
	
	return (segments, total_duration)

# python needs to die
counter = 0
async def segment(semaphore, preset, input, output, start, duration, total):
	async with semaphore:
		global counter
		segment_encoder = await asyncio.subprocess.create_subprocess_exec(*format_array(shlex.split(preset["segment_encoder"]),
			input = input,
			output = output,
			start = start,
			duration = duration,
		), stdout = asyncio.subprocess.PIPE, stderr = asyncio.subprocess.PIPE)
		if await segment_encoder.wait() != 0:
			stderr = segment_encoder.stderr.decode(sys.stdout.encoding)
			log.error("error encoding segment " + str(i) + " at " + str(start) + "seconds: " + segment_encoder.stderr)
			sys.exit(-1)
		counter += 1
		log.info("segment " + str(counter) + " / " + str(total) + " done")

async def main():
	global CONFIG
	
	log.basicConfig(level=log.DEBUG)
	parser = argparse.ArgumentParser(description = "Removes silence from (lecture) records", allow_abbrev = False)
	parser.add_argument("--input", "-i", help = "specifies input file", required = True)
	parser.add_argument("--output", "-o", help = "specifies output file (supports {base} and {ext} substitution)")
	parser.add_argument("--config", "-c", help = "path to config")
	parser.add_argument("--preset", "-p", help = "selects encoder string with given name in config")
	parser.add_argument("--parallel", "-j", help = "number of parallel ffmpeg instances (defaults to logical core count / 4)", type = int)

	args = parser.parse_args()

	if not os.path.isfile(args.input):
		log.error("file not found: " + args.input)
		sys.exit(-1)
	input = args.input

	if args.config is not None:
		with open(args.config) as file:
			log.info("loaded additional presets from " + args.config)
			data = json.load(file)
			CONFIG |= data

	preset = args.preset or "default"
	log.info("using preset " + preset)
	if preset not in CONFIG["presets"]:
		log.error("unable to find preset: " + args.preset)
		log.info("available presets: " + CONFIG.presets.keys())
		sys.exit(-1)
	preset = CONFIG["presets"][preset]

	output = args.output or preset["output"]
	input_filename = os.path.basename(args.input)
	(base, ext) = os.path.splitext(input_filename)
	output = output.format(base = base, ext = ext)

	if os.path.exists(output):
		log.error("Ouput file already exists: " + output)
		sys.exit(-1)
	
	# just a guess, too many threads and the context switches cost more than you gain
	job_count = max(args.parallel or math.floor(os.cpu_count() / 4), 1)

	log.info("detecting silence segments... this may take a few seconds")
	format_array(shlex.split(preset["silencedetect"]), input = input)
	silencedetect = subprocess.run(format_array(shlex.split(preset["silencedetect"]), input = input), text = True, capture_output = True)
	if silencedetect.returncode != 0:
		log.error("silencedetect exited with non-zero return code: \n" + silencedetect.stderr)
		sys.exit(-1)

	# parse ffmpeg output
	(segments, total_duration) = parse_silencedetect(silencedetect.stderr)
	log.info("Found total of " + str(len(segments)) + " segments with total duration of " + str(total_duration) + " seconds of silence.")

	# start processing in temporary directory
	# create temporary directory for processing of segments
	with tempfile.TemporaryDirectory() as dir:
		log.info("Extracting segments in temporary directory " + dir + " with " + str(job_count) + " jobs...")
		concat = ""
		i = 0
		
		semaphore = asyncio.Semaphore(4)
		tasks = []
		for (type, start, end) in segments:
			duration = end - start
			
			if type == SegmentType.AUDIBLE and duration > 0:
				seg_file = os.path.join(dir, "seg_" + str(i) + ".nut")
				concat += "file '" + seg_file + "'" + "\n"
				tasks.append(asyncio.create_task(segment(semaphore, preset, input, seg_file, start, duration, len(segments))))

			# counting audible segments is important to display accurate progress
			i += 1
		
		# TODO: status report with something else...
		await asyncio.gather(*tasks)

		concat_file = os.path.join(dir, "concat.txt")
		print(concat, file = open(concat_file, "w"))
		log.info("Reassemble segments...")
		subprocess.check_output([
			"ffmpeg",
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
		
asyncio.run(main())