# Legacy
This used to be a very hack and dirty bash script. Due to various problems (who would have guessed) I decided to rewrite it in Python. Which turned out to be a very bad idea as well, but I guess I still improved it. If you are interested in the old bash script, you can find it right here: https://github.com/chrisliebaer/desilence/blob/6e9aefc69177639dba9de4edb69387e2f3c95c7d/desilence

![Sometimes...](https://imgs.xkcd.com/comics/automation.png)

# Usage
Help output is integrated in the script and can be accessed by calling `python desilence.py --help`.

# What
This is a simple helper script that drives the ffmpeg binary in order to detect and remove silent segments from any video. It's main purpose is to remove silent segments from my universities lecture recordings but it also works for any other form of content. You can even use it for making low effort jump cut videos. While this script offers a ready to go configuration, I assume that the user still has some knowledge about how ffmpeg works, since custom configurations require you to provide mostly complete ffmpeg invocations.

# Configuration
The encoding process can be controlled via the `--preset` option. If no preset is specified, the `default` preset will be used and is embedded in the script itself. The config file is a JSON encoded file with the following layout (note that even the `default` preset can be overridden):

```json
{
	"presets": {
		"default": {
			"output": "{base}_desilenced.mkv",
			"silencedetect": "ffmpeg -hide_banner -nostdin -i {input} -af silencedetect=n=-50dB:d=0.5 -vn -f null -",
			"segment_encoder": "ffmpeg -hide_banner -nostdin -ss {start} -i {input} -t {duration} -c:v libx264 -crf 26 -preset slow -c:a libopus -b:a 96k -y {output}"
		},
		"nevc": {
			"output": "{base}_desilenced.mkv",
			"silencedetect": "ffmpeg -hide_banner -nostdin -i {input} -af silencedetect=n=-50dB:d=0.5 -vn -f null -",
			"segment_encoder": "ffmpeg -hide_banner -hwaccel cuvid -nostdin -ss {start} -i {input} -t {duration} -c:v hevc_nvenc -rc constqp -qp 38 -preset slow -c:a libopus -b:a 32k -y {output}"
		}
	}
}
```

It is important for these invocations to be compatible with how the script is interacting with ffmpeg. If you know your way around ffmpeg, you will know how to use these. Otherwise you are out of luck, sadly there is no easy solution since video encoding is inherently complex and more often than not needs to be fine tuned to the situation at hand. As a small note, the `segment_encoder` is used as an intermediate step and especially the `{output}` field is going to use an internal name and format, so don't make assumptions. You can not configure the final assembly step, since I couldn't find any use but a lot of potential to cause mayhem.

# How
This script uses [ffmpegs silencedetect filter)](https://ffmpeg.org/ffmpeg-filters.html#silencedetect) which will print out all detected silence. While this output is not declared stable, I haven't seen it change in many years. After that, a temporary directory is created and multiple ffmpeg processes are spawned to extract individual segments from the video into this directory. At the same time the segment is encoded with the configured encoder settings since precise cuts are otherwise impossible (It should actually be possible to pipe raw data into another ffmpeg process but I was unable to get it to work without using the ffmpeg API directly). After that, all files are reassembled into the final video.

# Contribution
Feel free to contribute changes. I am not a Python developer, as you might be able to tell by look at the code, but I also didn't spend a great deal of time to make a clean solution. If you feel like you could improve something, go ahead, just keep it simple and refrain from including external depencies, because as I said: I'm not a Python developer, I just want it to run, without learning yet another broken mess dependency resolver. It does the job and it took me a reasonable amount of time that I'm probably already not going to save by using this tool by myself, but at least I'm now more likely to remain calm. Just like my teachers are around 20% of their lectures :)))