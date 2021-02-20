# A few words of warning
This is a very hacky script. It relies on ffmpeg output that has not been declared stable. It may break with any ffmpeg update. It was not written to be reliably but to get the job done, since I wanted to save time, not lose time. This means that this is not something you can blindly run. It stores various information in temporary folders and does not check if the commands ran successfully. You may very well end up with an empty variable that ends up executing a huge `rm` operation. Please take care!

The results are amazing tho. Which is also why I released it anyway: It's usefull and there is no better solution to my knowledge.

![Sometimes...](https://imgs.xkcd.com/comics/automation.png)
