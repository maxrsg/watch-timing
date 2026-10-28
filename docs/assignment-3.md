## The problem
The application prompted the user to allow the site using the camera, each time you wanted to take a photo, instead of just asking once.
Not only was this annoying, but it also disrupted the user experience by constantly having to press the allow button. 

I provided a description of the issue to the agent, clearly describing what happened and what actions to take in the user interface to reproduce the issue,
asking it to investigate the cause of the problem.

The agent had three theories of what was causing the issue:
1. The iOS browser doesn't keep a "remembered" camera grant, and the app stops its stream every time
2. The origin isn't stable or trusted, so the grant can't stick
3. Duplicate or racing getUserMedia calls in the app (StrictMode, remounts)

I asked it to investigate theory one closer, it seemed to make sense and the nature of the issue seemed to indicate it had something to do with
the os and/or browser. The agent came to the conclusion that this theory was indeed right and it is mostly a browser issue that can't be solved
by simply changing some code. What it did get wrong however, was that it thought it might be connected to a bug in WebKit, but when it investigated it futher
it found no sources indicating that this might be an issue. 


To alleviate the issue the agent did come up with a small rework of how the application mounts the camera, not resetting it as soon as an image is taken, but rather letting it stay opened in the background. This alleviates the issue somewhat, making it less annoying when developing and testing it out. The agent
did also point out that it is possible to make safari skip the prompt by changing the website settings in the browser as well. 