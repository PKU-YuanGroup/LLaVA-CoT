# Prediction interface for Cog ⚙️
# https://cog.run/python


import os
import subprocess
import time
from threading import Thread
import torch
from PIL import Image
from transformers import MllamaForConditionalGeneration, AutoProcessor
from transformers.generation.streamers import TextIteratorStreamer
from cog import BasePredictor, Input, Path, ConcatenateIterator


MODEL_CACHE = "model_cache"
MODEL_URL = f"https://weights.replicate.delivery/default/Xkev/Llama-3.2V-11B-cot/{MODEL_CACHE}.tar"

os.environ.update(
    {
        "HF_DATASETS_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HOME": MODEL_CACHE,
        "TORCH_HOME": MODEL_CACHE,
        "HF_DATASETS_CACHE": MODEL_CACHE,
        "TRANSFORMERS_CACHE": MODEL_CACHE,
        "HUGGINGFACE_HUB_CACHE": MODEL_CACHE,
    }
)


def download_weights(url, dest):
    start = time.time()
    print("downloading url: ", url)
    print("downloading to: ", dest)
    subprocess.check_call(["pget", "-x", url, dest], close_fds=False)
    print("downloading took: ", time.time() - start)


class Predictor(BasePredictor):
    def setup(self) -> None:
        """Load the model into memory to make running multiple predictions efficient"""

        if not os.path.exists(MODEL_CACHE):
            download_weights(MODEL_URL, MODEL_CACHE)

        self.model = MllamaForConditionalGeneration.from_pretrained(
            f"{MODEL_CACHE}/Xkev/Llama-3.2V-11B-cot",
            torch_dtype=torch.bfloat16,
            device_map="auto",
        )
        self.processor = AutoProcessor.from_pretrained(
            f"{MODEL_CACHE}/Xkev/Llama-3.2V-11B-cot"
        )

    def predict(
        self,
        prompt: str = Input(
            description="Text prompt",
            default="If I had to write a haiku for this one, it would be: ",
        ),
        image: Path = Input(description="Grayscale input image"),
        max_new_tokens: int = Input(
            description="Max number of generated tokens", default=1024
        ),
        temperature: float = Input(
            description="Adjusts randomness of outputs, greater than 1 is random and 0 is deterministic, 0.75 is a good starting value.",
            ge=0,
            le=5,
            default=0.9,
        ),
        top_p: float = Input(
            description="When decoding text, samples from the top p percentage of most likely tokens; lower to ignore less likely tokens, used when temperature > 0",
            ge=0.0,
            le=1.0,
            default=0.95,
        ),
    ) -> ConcatenateIterator[str]:
        """Run a single prediction on the model"""
        messages = [
            {
                "role": "user",
                "content": [{"type": "image"}, {"type": "text", "text": prompt}],
            }
        ]

        image = Image.open(str(image)).convert("RGB")
        input_text = self.processor.apply_chat_template(
            messages, add_generation_prompt=True
        )
        inputs = self.processor(
            image, input_text, add_special_tokens=False, return_tensors="pt"
        ).to(self.model.device)

        streamer = TextIteratorStreamer(
            self.processor, skip_special_tokens=True, skip_prompt=True
        )
        generation_kwargs = dict(
            inputs,
            streamer=streamer,
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0,
            temperature=temperature,
            top_p=top_p,
        )

        with torch.inference_mode():
            thread = Thread(target=self.model.generate, kwargs=generation_kwargs)
            thread.start()
            for new_token in streamer:
                yield new_token
            thread.join()
