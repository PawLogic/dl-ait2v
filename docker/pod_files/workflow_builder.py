#!/usr/bin/env python3
"""
Workflow template loader with placeholder injection.
Uses workflow_ltx2_enhanced.json as base template.

Based on test_720p.py production configuration:
- Resolution: 1280x736
- img_compression: 23
- fps: 30 (default, configurable 1-60)
- steps: 8
- cfg: 1.0

Mode 3: Multi-keyframe support using LTXVAddGuideMulti (KJNodes)
- Supports 1-9 keyframe images with configurable frame positions and strengths
- Frame positions: "first", "last", or 0.0-1.0 normalized
"""
import json
import math
import copy
import os
from typing import Dict, Any, List, Optional, Union


class WorkflowBuilder:
    """Build workflow from enhanced template with parameter injection."""

    # Maximum keyframes supported
    MAX_KEYFRAMES = 9

    def __init__(
        self,
        template_path: str = "/comfyui/workflows/ltx2_enhanced.json",
        audio_gen_template_path: str = "/comfyui/workflows/ltx2_audio_gen.json",
        multiframe_template_path: str = "/comfyui/workflows/ltx2_multiframe.json"
    ):
        """Load workflow templates."""
        with open(template_path, 'r') as f:
            self.template = json.load(f)

        # Load audio generation template if available
        self.audio_gen_template = None
        if audio_gen_template_path and os.path.exists(audio_gen_template_path):
            with open(audio_gen_template_path, 'r') as f:
                self.audio_gen_template = json.load(f)
            print(f"Audio generation template loaded: {audio_gen_template_path}")

        # Load multiframe template if available
        self.multiframe_template = None
        if multiframe_template_path and os.path.exists(multiframe_template_path):
            with open(multiframe_template_path, 'r') as f:
                self.multiframe_template = json.load(f)
            print(f"Multiframe template loaded: {multiframe_template_path}")

    def build_workflow(
        self,
        image_name: str,
        audio_name: str,
        audio_duration: float,
        prompt_positive: str,
        prompt_negative: str,
        seed: int,
        width: int = 1280,
        height: int = 736,
        fps: int = 30,
        steps: int = 8,
        cfg_scale: float = 1.0,
        lora_distilled: float = 0.6,
        lora_detailer: float = 1.0,
        lora_camera: float = 0.3,
        lora_i2v: float = 0.8,
        img_compression: int = 23,
        img_strength: float = 1.0,
        buffer_seconds: float = 1.0,
    ) -> dict:
        """
        Inject parameters into workflow template.

        Args:
            image_name: Uploaded image filename in ComfyUI
            audio_name: Uploaded audio filename in ComfyUI
            audio_duration: Audio duration in seconds
            prompt_positive: Positive prompt text
            prompt_negative: Negative prompt text
            seed: Random seed for generation
            width: Video width (must be divisible by 32)
            height: Video height (must be divisible by 32)
            fps: Frames per second (default 30)
            steps: Sampling steps (default 8)
            cfg_scale: CFG scale (default 1.0)
            lora_distilled: Distilled LoRA strength (default 0.6)
            lora_detailer: Detailer LoRA strength (default 1.0)
            lora_camera: Camera LoRA strength (default 0.3)
            lora_i2v: I2V Adapter LoRA strength (default 0.8)
            img_compression: Image compression level (default 23, lower = better quality)
            img_strength: First frame injection strength (default 0.9)
            buffer_seconds: Extra buffer time beyond input duration (default 1.0s)

        Returns:
            Complete workflow ready for ComfyUI execution
        """
        # Calculate frame count to ensure video duration >= audio duration + buffer
        # Formula: num_frames = ceil((audio_duration + buffer_seconds) * fps) + 1
        # Buffer ensures video has extra frames beyond audio
        total_duration = audio_duration + buffer_seconds
        num_frames = math.ceil(total_duration * fps) + 1

        # Ensure minimum frames (at least 1 second of video)
        if num_frames < 30:
            num_frames = 30

        # Create parameter mapping for placeholder replacement
        params = {
            "INPUT_IMAGE": image_name,
            "INPUT_AUDIO": audio_name,
            "WIDTH": width,
            "HEIGHT": height,
            "NUM_FRAMES": num_frames,
            "AUDIO_DURATION": audio_duration,
            "FPS": fps,
            "PROMPT_POSITIVE": prompt_positive,
            "PROMPT_NEGATIVE": prompt_negative,
            "SEED": seed,
            "STEPS": steps,
            "CFG_SCALE": cfg_scale,
            "LORA_DISTILLED_STRENGTH": lora_distilled,
            "LORA_DETAILER_STRENGTH": lora_detailer,
            "LORA_CAMERA_STRENGTH": lora_camera,
            "LORA_I2V_STRENGTH": lora_i2v,
            "IMG_COMPRESSION": img_compression,
            "IMG_STRENGTH": img_strength,
        }

        # Deep copy template and inject parameters
        workflow = self._inject_parameters(self.template, params)

        # Remove LoRA nodes with strength=0 to save GPU memory and compute
        workflow = self._remove_zero_strength_loras(workflow)

        return workflow

    def _inject_parameters(self, workflow: dict, params: Dict[str, Any]) -> dict:
        """Recursively replace placeholders with actual values."""
        workflow = copy.deepcopy(workflow)

        def replace_value(obj):
            if isinstance(obj, str):
                # Check if this string is a placeholder key
                if obj in params:
                    return params[obj]
                return obj
            elif isinstance(obj, dict):
                return {k: replace_value(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_value(item) for item in obj]
            else:
                return obj

        return replace_value(workflow)

    def _remove_zero_strength_loras(self, workflow: dict) -> dict:
        """
        Remove LoraLoaderModelOnly nodes with strength_model=0 and reconnect the chain.

        When a LoRA strength is 0, loading it wastes GPU memory and compute time.
        This method removes such nodes and rewires downstream references to the
        upstream model source, preserving the chain integrity.
        """
        removed = True
        while removed:
            removed = False
            for node_id in list(workflow.keys()):
                node = workflow[node_id]
                if node.get("class_type") != "LoraLoaderModelOnly":
                    continue
                strength = node["inputs"].get("strength_model", 1.0)
                if isinstance(strength, (int, float)) and strength == 0:
                    # Get upstream model reference (what this node receives)
                    upstream_ref = node["inputs"]["model"]
                    lora_name = node["inputs"].get("lora_name", "unknown")
                    # Replace all downstream references to [node_id, 0] with upstream_ref
                    for other_id, other_node in workflow.items():
                        if "inputs" not in other_node:
                            continue
                        for key, value in other_node["inputs"].items():
                            if isinstance(value, list) and len(value) == 2:
                                if str(value[0]) == str(node_id) and value[1] == 0:
                                    other_node["inputs"][key] = upstream_ref
                    # Remove the node
                    del workflow[node_id]
                    print(f"  [LoRA optimization] Removed {lora_name} (strength=0, node {node_id})")
                    removed = True
                    break  # Restart scan since workflow changed
        return workflow

    def get_video_params(self, audio_duration: float, fps: int = 24, buffer_seconds: float = 1.0) -> dict:
        """
        Calculate video parameters from audio duration.
        Ensures video duration >= audio duration + buffer.

        Args:
            audio_duration: Audio duration in seconds
            fps: Frames per second
            buffer_seconds: Extra buffer time beyond audio duration (default 1.0s)

        Returns:
            dict with num_frames, actual_duration, fps, audio_duration, buffer_seconds
        """
        # Ensure video is at least as long as audio + buffer
        total_duration = audio_duration + buffer_seconds
        num_frames = math.ceil(total_duration * fps) + 1
        if num_frames < 30:
            num_frames = 30

        return {
            "num_frames": num_frames,
            "actual_duration": num_frames / fps,
            "audio_duration": audio_duration,
            "buffer_seconds": buffer_seconds,
            "fps": fps,
        }

    def build_audio_gen_workflow(
        self,
        image_name: str,
        duration: float,
        prompt_positive: str,
        prompt_negative: str,
        seed: int,
        width: int = 1280,
        height: int = 736,
        fps: int = 30,
        steps: int = 8,
        cfg_scale: float = 1.0,
        lora_distilled: float = 0.6,
        lora_detailer: float = 1.0,
        lora_camera: float = 0.3,
        lora_i2v: float = 0.8,
        img_compression: int = 23,
        img_strength: float = 1.0,
        buffer_seconds: float = 1.0,
    ) -> dict:
        """
        Build workflow for Image-to-Video+Audio generation (no input audio).

        This mode generates both video and audio from just an image and duration.
        Uses LTXVEmptyLatentAudio to create empty audio latent for generation.

        Args:
            image_name: Uploaded image filename in ComfyUI
            duration: Target video/audio duration in seconds
            prompt_positive: Positive prompt text
            prompt_negative: Negative prompt text
            seed: Random seed for generation
            width: Video width (must be divisible by 32)
            height: Video height (must be divisible by 32)
            fps: Video frames per second (default 24)
            steps: Sampling steps (default 8)
            cfg_scale: CFG scale (default 1.0)
            lora_distilled: Distilled LoRA strength (default 0.6)
            lora_detailer: Detailer LoRA strength (default 1.0)
            lora_camera: Camera LoRA strength (default 0.3)
            lora_i2v: I2V Adapter LoRA strength (default 0.8)
            img_compression: Image compression level (default 23)
            img_strength: First frame injection strength (default 1.0)
            buffer_seconds: Extra buffer time beyond target duration (default 1.0s)

        Returns:
            Complete workflow ready for ComfyUI execution

        Raises:
            RuntimeError: If audio generation template is not loaded
        """
        if self.audio_gen_template is None:
            raise RuntimeError("Audio generation template not loaded")

        # Calculate video frames with buffer
        total_duration = duration + buffer_seconds
        num_frames = math.ceil(total_duration * fps) + 1
        if num_frames < 30:
            num_frames = 30

        # Calculate audio frames (25 Hz - LTX audio frame rate) - no buffer for audio
        audio_frames = math.ceil(duration * 25)
        if audio_frames < 25:
            audio_frames = 25

        # Create parameter mapping for placeholder replacement
        params = {
            "INPUT_IMAGE": image_name,
            "WIDTH": width,
            "HEIGHT": height,
            "NUM_FRAMES": num_frames,
            "AUDIO_FRAMES": audio_frames,
            "FPS": fps,
            "PROMPT_POSITIVE": prompt_positive,
            "PROMPT_NEGATIVE": prompt_negative,
            "SEED": seed,
            "STEPS": steps,
            "CFG_SCALE": cfg_scale,
            "LORA_DISTILLED_STRENGTH": lora_distilled,
            "LORA_DETAILER_STRENGTH": lora_detailer,
            "LORA_CAMERA_STRENGTH": lora_camera,
            "LORA_I2V_STRENGTH": lora_i2v,
            "IMG_COMPRESSION": img_compression,
            "IMG_STRENGTH": img_strength,
        }

        # Deep copy template and inject parameters
        workflow = self._inject_parameters(self.audio_gen_template, params)

        # Remove LoRA nodes with strength=0 to save GPU memory and compute
        workflow = self._remove_zero_strength_loras(workflow)

        return workflow

    def get_audio_gen_params(self, duration: float, fps: int = 24, buffer_seconds: float = 1.0) -> dict:
        """
        Calculate video and audio parameters for audio generation mode.

        Args:
            duration: Target duration in seconds
            fps: Video frames per second
            buffer_seconds: Extra buffer time beyond target duration (default 1.0s)

        Returns:
            dict with num_frames, audio_frames, actual_duration, fps, buffer_seconds
        """
        total_duration = duration + buffer_seconds
        num_frames = math.ceil(total_duration * fps) + 1
        if num_frames < 30:
            num_frames = 30

        # Audio frames without buffer (audio matches target duration)
        audio_frames = math.ceil(duration * 25)
        if audio_frames < 25:
            audio_frames = 25

        return {
            "num_frames": num_frames,
            "audio_frames": audio_frames,
            "actual_video_duration": num_frames / fps,
            "actual_audio_duration": audio_frames / 25,
            "target_duration": duration,
            "buffer_seconds": buffer_seconds,
            "fps": fps,
        }

    def _calculate_frame_index(
        self,
        position: Union[str, float],
        total_frames: int,
        frame_alignment: int = 8
    ) -> int:
        """
        Convert frame position to absolute frame index.

        Args:
            position: "first", "last", or 0.0-1.0 normalized position
            total_frames: Total number of video frames
            frame_alignment: Frame alignment interval (default 8, set to 1 to disable)

        Returns:
            Absolute frame index (0-indexed, explicit value - never -1)
        """
        last_frame = total_frames - 1

        if position == "first":
            return 0

        if position == "last":
            # v57 fix: Apply frame alignment to last frame too
            # This ensures all keyframes are on consistent 8-frame boundaries
            if frame_alignment > 1:
                aligned = (last_frame // frame_alignment) * frame_alignment
                return max(0, aligned)
            return last_frame

        # Normalize to float
        try:
            pos = float(position)
        except (TypeError, ValueError):
            return 0

        # Clamp to valid range
        pos = max(0.0, min(1.0, pos))

        if pos >= 1.0:
            # Same alignment logic as "last"
            if frame_alignment > 1:
                aligned = (last_frame // frame_alignment) * frame_alignment
                return max(0, aligned)
            return last_frame

        if pos <= 0.0:
            return 0

        # Calculate intermediate frame index
        idx = int(pos * last_frame)

        # Apply frame alignment if alignment > 1
        if frame_alignment > 1:
            idx = (idx // frame_alignment) * frame_alignment

        # Ensure we don't exceed bounds
        return max(0, min(idx, last_frame))

    def build_multiframe_workflow(
        self,
        keyframes: List[Dict[str, Any]],
        audio_name: Optional[str] = None,
        audio_duration: Optional[float] = None,
        duration: Optional[float] = None,
        prompt_positive: str = "",
        prompt_negative: str = "",
        seed: int = 0,
        width: int = 1280,
        height: int = 736,
        fps: int = 30,
        steps: int = 8,
        cfg_scale: float = 1.0,
        lora_distilled: float = 0.6,
        lora_detailer: float = 1.0,
        lora_camera: float = 0.3,
        lora_i2v: float = 0.8,
        img_compression: int = 23,
        trim_to_audio: bool = False,
        frame_alignment: int = 8,
        buffer_seconds: float = 1.0,
    ) -> dict:
        """
        Build workflow for multi-keyframe video generation (Mode 3).

        Uses LTXVAddGuideMulti from KJNodes for multi-image guide injection.

        Args:
            keyframes: List of keyframe dicts with keys:
                - image_name: Uploaded image filename in ComfyUI
                - frame_position: "first", "last", or 0.0-1.0 normalized
                - strength: Guide strength 0.0-1.0 (default 1.0)
            audio_name: Uploaded audio filename (Mode 3a: lip-sync)
            audio_duration: Audio duration in seconds (Mode 3a)
            duration: Target duration in seconds (Mode 3b: audio generation)
            prompt_positive: Positive prompt text
            prompt_negative: Negative prompt text
            seed: Random seed for generation
            width: Video width (must be divisible by 32)
            height: Video height (must be divisible by 32)
            fps: Frames per second (default 30)
            steps: Sampling steps (default 8)
            cfg_scale: CFG scale (default 1.0)
            lora_distilled: Distilled LoRA strength (default 0.6)
            lora_detailer: Detailer LoRA strength (default 1.0)
            lora_camera: Camera LoRA strength (default 0.3)
            lora_i2v: I2V Adapter LoRA strength (default 0.8)
            img_compression: Image compression level (default 23)
            trim_to_audio: Whether to trim video to audio length (default False)
            frame_alignment: Frame alignment interval for keyframes (default 8, set to 1 to disable)
            buffer_seconds: Extra buffer time beyond input duration (default 1.0s)

        Returns:
            Complete workflow ready for ComfyUI execution

        Raises:
            ValueError: If keyframes is empty or exceeds MAX_KEYFRAMES
            RuntimeError: If multiframe template is not loaded
        """
        if self.multiframe_template is None:
            raise RuntimeError("Multiframe template not loaded")

        if not keyframes:
            raise ValueError("At least one keyframe is required")
        if len(keyframes) > self.MAX_KEYFRAMES:
            raise ValueError(f"Maximum {self.MAX_KEYFRAMES} keyframes supported")

        # Determine mode and calculate frames (with buffer)
        is_audio_gen = audio_name is None and duration is not None
        if is_audio_gen:
            # Mode 3b: Audio generation
            total_duration = duration + buffer_seconds
            num_frames = math.ceil(total_duration * fps) + 1
            audio_frames = math.ceil(duration * 25)  # Audio frames without buffer
        else:
            # Mode 3a: Lip-sync with input audio
            total_duration = audio_duration + buffer_seconds
            num_frames = math.ceil(total_duration * fps) + 1
            audio_frames = None

        if num_frames < 30:
            num_frames = 30

        # Start with base template
        workflow = copy.deepcopy(self.multiframe_template)

        # Node ID counter for dynamic nodes (start from 400 to avoid conflicts)
        node_id = 400

        # Create load/resize/preprocess nodes for each keyframe
        keyframe_node_ids = []
        for i, kf in enumerate(keyframes):
            image_name = kf.get("image_name", "")
            frame_position = kf.get("frame_position", "first" if i == 0 else "last")
            strength = kf.get("strength", 1.0)

            # LoadImage node
            load_node_id = str(node_id)
            workflow[load_node_id] = {
                "inputs": {
                    "image": image_name,
                    "upload": "image"
                },
                "class_type": "LoadImage",
                "_meta": {"title": f"Load Keyframe {i+1}"}
            }
            node_id += 1

            # ImageResizeKJv2 node
            resize_node_id = str(node_id)
            workflow[resize_node_id] = {
                "inputs": {
                    "image": [load_node_id, 0],
                    "width": width,
                    "height": height,
                    "upscale_method": "lanczos",
                    "keep_proportion": "pad",
                    "pad_color": "0, 0, 0",
                    "crop_position": "center",
                    "divisible_by": 32
                },
                "class_type": "ImageResizeKJv2",
                "_meta": {"title": f"Resize Keyframe {i+1}"}
            }
            node_id += 1

            # LTXVPreprocess node
            preprocess_node_id = str(node_id)
            workflow[preprocess_node_id] = {
                "inputs": {
                    "image": [resize_node_id, 0],
                    "img_compression": img_compression
                },
                "class_type": "LTXVPreprocess",
                "_meta": {"title": f"Preprocess Keyframe {i+1}"}
            }
            node_id += 1

            # Calculate frame index
            frame_idx = self._calculate_frame_index(frame_position, num_frames, frame_alignment)

            keyframe_node_ids.append({
                "preprocess_node_id": preprocess_node_id,
                "frame_idx": frame_idx,
                "strength": strength
            })

        # Create LTXVAddGuideMulti node
        # CORRECT FORMAT based on v49 validation error:
        # - Selection value: "num_guides": "3" (string)
        # - All child inputs with prefix: "num_guides.image_1", "num_guides.frame_idx_1", etc.
        # NOTE: Validation passes with this format, but execution fails because
        # build_nested_inputs() doesn't correctly transform the flat inputs to nested dict.
        # This appears to be a ComfyUI v3 DynamicCombo API limitation.

        guide_multi_inputs = {
            "positive": ["164", 0],  # From LTXVConditioning
            "negative": ["164", 1],
            "vae": ["184", 2],       # From CheckpointLoaderSimple
            "latent": ["162", 0],    # From EmptyLTXVLatentVideo
            "num_guides": str(len(keyframes))  # Selection value as string
        }

        # Add ALL dynamic inputs with "num_guides." prefix
        for i, kf_data in enumerate(keyframe_node_ids):
            idx = i + 1  # LTXVAddGuideMulti uses 1-indexed inputs
            # Image input - connection format [node_id, slot_index]
            guide_multi_inputs[f"num_guides.image_{idx}"] = [kf_data["preprocess_node_id"], 0]
            # Frame index - direct value (NOT array, array would be interpreted as link)
            guide_multi_inputs[f"num_guides.frame_idx_{idx}"] = kf_data["frame_idx"]
            # Strength - direct value (NOT array, array would be interpreted as link)
            guide_multi_inputs[f"num_guides.strength_{idx}"] = kf_data["strength"]

        guide_multi_node_id = str(node_id)
        workflow[guide_multi_node_id] = {
            "inputs": guide_multi_inputs,
            "class_type": "LTXVAddGuideMulti",
            "_meta": {"title": "Multi-Keyframe Guides"}
        }
        node_id += 1

        # Update conditioning to use guide outputs
        # LTXVAddGuideMulti outputs: (positive, negative, latent)
        workflow["153"]["inputs"]["positive"] = [guide_multi_node_id, 0]  # CFGGuider positive
        workflow["153"]["inputs"]["negative"] = [guide_multi_node_id, 1]  # CFGGuider negative

        # Create audio handling nodes based on mode
        if is_audio_gen:
            # Mode 3b: Generate audio with LTXVEmptyLatentAudio
            empty_audio_node_id = str(node_id)
            workflow[empty_audio_node_id] = {
                "inputs": {
                    "frames_number": audio_frames,
                    "frame_rate": 25,
                    "batch_size": 1,
                    "audio_vae": ["171", 0]
                },
                "class_type": "LTXVEmptyLatentAudio",
                "_meta": {"title": "Empty Audio Latent"}
            }
            node_id += 1

            # LTXVConcatAVLatent - combine video and audio latents
            concat_node_id = str(node_id)
            workflow[concat_node_id] = {
                "inputs": {
                    "video_latent": [guide_multi_node_id, 2],  # Latent from guide node
                    "audio_latent": [empty_audio_node_id, 0]
                },
                "class_type": "LTXVConcatAVLatent",
                "_meta": {"title": "Concat AV Latent"}
            }
            node_id += 1

            # Audio decode for output
            audio_decode_node_id = str(node_id)
            workflow[audio_decode_node_id] = {
                "inputs": {
                    "samples": ["245", 1],  # Audio from LTXVSeparateAVLatent
                    "audio_vae": ["171", 0]
                },
                "class_type": "LTXVAudioVAEDecode",
                "_meta": {"title": "Audio VAE Decode"}
            }
            node_id += 1

            audio_output_ref = [audio_decode_node_id, 0]

        else:
            # Mode 3a: Use input audio
            # LoadAudio node
            load_audio_node_id = str(node_id)
            workflow[load_audio_node_id] = {
                "inputs": {
                    "audio": audio_name
                },
                "class_type": "LoadAudio",
                "_meta": {"title": "Load Audio"}
            }
            node_id += 1

            # TrimAudioDuration node
            trim_audio_node_id = str(node_id)
            workflow[trim_audio_node_id] = {
                "inputs": {
                    "audio": [load_audio_node_id, 0],
                    "max_duration": audio_duration,
                    "duration": audio_duration,
                    "start_index": 0
                },
                "class_type": "TrimAudioDuration",
                "_meta": {"title": "Trim Audio"}
            }
            node_id += 1

            # Audio VAE Encode
            audio_encode_node_id = str(node_id)
            workflow[audio_encode_node_id] = {
                "inputs": {
                    "audio": [trim_audio_node_id, 0],
                    "audio_vae": ["171", 0]
                },
                "class_type": "LTXVAudioVAEEncode",
                "_meta": {"title": "Audio VAE Encode"}
            }
            node_id += 1

            # Audio noise mask
            solid_mask_node_id = str(node_id)
            workflow[solid_mask_node_id] = {
                "inputs": {
                    "value": 0,
                    "width": width,
                    "height": height
                },
                "class_type": "SolidMask",
                "_meta": {"title": "Audio Mask"}
            }
            node_id += 1

            # SetLatentNoiseMask
            set_mask_node_id = str(node_id)
            workflow[set_mask_node_id] = {
                "inputs": {
                    "samples": [audio_encode_node_id, 0],
                    "mask": [solid_mask_node_id, 0]
                },
                "class_type": "SetLatentNoiseMask",
                "_meta": {"title": "Set Noise Mask"}
            }
            node_id += 1

            # LTXVConcatAVLatent - combine video and audio latents
            concat_node_id = str(node_id)
            workflow[concat_node_id] = {
                "inputs": {
                    "video_latent": [guide_multi_node_id, 2],
                    "audio_latent": [set_mask_node_id, 0]
                },
                "class_type": "LTXVConcatAVLatent",
                "_meta": {"title": "Concat AV Latent"}
            }
            node_id += 1

            audio_output_ref = [trim_audio_node_id, 0]

        # Add SamplerCustomAdvanced node
        sampler_node_id = "161"
        workflow[sampler_node_id] = {
            "inputs": {
                "noise": ["178", 0],
                "guider": ["153", 0],
                "sampler": ["154", 0],
                "sigmas": ["238", 0],
                "latent_image": [concat_node_id, 0]
            },
            "class_type": "SamplerCustomAdvanced",
            "_meta": {"title": "Sampler"}
        }

        # Add VHS_VideoCombine output node
        video_output_node_id = "190"
        workflow[video_output_node_id] = {
            "inputs": {
                "frame_rate": fps,
                "loop_count": 0,
                "filename_prefix": "ltx2_multiframe",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": 19,
                "save_metadata": True,
                "trim_to_audio": trim_to_audio,
                "pingpong": False,
                "save_output": True,
                "images": ["234", 0],
                "audio": audio_output_ref
            },
            "class_type": "VHS_VideoCombine",
            "_meta": {"title": "Video Output"}
        }

        # Inject remaining parameters
        params = {
            "WIDTH": width,
            "HEIGHT": height,
            "NUM_FRAMES": num_frames,
            "FPS": fps,
            "PROMPT_POSITIVE": prompt_positive,
            "PROMPT_NEGATIVE": prompt_negative,
            "SEED": seed,
            "STEPS": steps,
            "CFG_SCALE": cfg_scale,
            "LORA_DISTILLED_STRENGTH": lora_distilled,
            "LORA_DETAILER_STRENGTH": lora_detailer,
            "LORA_CAMERA_STRENGTH": lora_camera,
            "LORA_I2V_STRENGTH": lora_i2v,
        }

        workflow = self._inject_parameters(workflow, params)

        # Remove LoRA nodes with strength=0 to save GPU memory and compute
        workflow = self._remove_zero_strength_loras(workflow)

        return workflow

    def get_multiframe_params(
        self,
        keyframes: List[Dict[str, Any]],
        duration: Optional[float] = None,
        audio_duration: Optional[float] = None,
        fps: int = 30,
        frame_alignment: int = 8,
        buffer_seconds: float = 1.0,
        auto_buffer_guide: Union[bool, str] = True
    ) -> dict:
        """
        Calculate video/audio parameters for multiframe mode.

        Args:
            keyframes: List of keyframe definitions
            duration: Target duration for audio generation mode
            audio_duration: Audio duration for lip-sync mode
            fps: Video frames per second
            frame_alignment: Frame alignment interval (default 8, set to 1 to disable)
            buffer_seconds: Extra buffer time beyond input duration (default 1.0s)
            auto_buffer_guide: Buffer guide strategy (True/"add_node", "extend_last", or False/"none")

        Returns:
            dict with num_frames, audio_frames, keyframe info, buffer_seconds, buffer_strategy, etc.
        """
        is_audio_gen = audio_duration is None and duration is not None

        if is_audio_gen:
            target_duration = duration
            total_duration = duration + buffer_seconds
            num_frames = math.ceil(total_duration * fps) + 1
            audio_frames = math.ceil(duration * 25)  # Audio without buffer
        else:
            target_duration = audio_duration
            total_duration = audio_duration + buffer_seconds
            num_frames = math.ceil(total_duration * fps) + 1
            audio_frames = None

        if num_frames < 30:
            num_frames = 30

        # Calculate frame indices for each keyframe
        keyframe_info = []
        for i, kf in enumerate(keyframes):
            position = kf.get("frame_position", "first" if i == 0 else "last")
            frame_idx = self._calculate_frame_index(position, num_frames, frame_alignment)
            keyframe_info.append({
                "position": position,
                "frame_idx": frame_idx,
                "strength": kf.get("strength", 1.0)
            })

        # Normalize buffer strategy
        if auto_buffer_guide is True or auto_buffer_guide == "add_node":
            buffer_strategy = "add_node"
        elif auto_buffer_guide == "extend_last":
            buffer_strategy = "extend_last"
        else:
            buffer_strategy = "none"

        # Check if buffer guide will be applied
        buffer_guide_applied = False
        if buffer_seconds > 0 and buffer_strategy != "none" and len(keyframe_info) > 0:
            buffer_end_frame = self._calculate_frame_index("last", num_frames, frame_alignment)
            last_kf_frame = keyframe_info[-1]["frame_idx"]
            if last_kf_frame < buffer_end_frame:
                buffer_guide_applied = True

        return {
            "num_frames": num_frames,
            "audio_frames": audio_frames,
            "actual_video_duration": num_frames / fps,
            "target_duration": target_duration,
            "buffer_seconds": buffer_seconds,
            "fps": fps,
            "mode": "audio_gen" if is_audio_gen else "lip_sync",
            "num_keyframes": len(keyframes),
            "keyframes": keyframe_info,
            "frame_alignment": frame_alignment,
            "buffer_strategy": buffer_strategy,
            "buffer_guide_applied": buffer_guide_applied
        }

    def build_multiframe_chained_workflow(
        self,
        keyframes: List[Dict[str, Any]],
        audio_name: Optional[str] = None,
        audio_duration: Optional[float] = None,
        duration: Optional[float] = None,
        prompt_positive: str = "",
        prompt_negative: str = "",
        seed: int = 0,
        width: int = 1280,
        height: int = 736,
        fps: int = 30,
        steps: int = 8,
        cfg_scale: float = 1.0,
        lora_distilled: float = 0.6,
        lora_detailer: float = 1.0,
        lora_camera: float = 0.3,
        lora_i2v: float = 0.8,
        img_compression: int = 23,
        trim_to_audio: bool = False,
        frame_alignment: int = 8,
        buffer_seconds: float = 1.0,
        auto_buffer_guide: Union[bool, str] = True,
    ) -> dict:
        """
        Build workflow for multi-keyframe video generation using chained LTXVAddGuide nodes (Mode 4).

        This is an alternative to build_multiframe_workflow that uses individual chained
        LTXVAddGuide nodes instead of LTXVAddGuideMulti. This approach avoids the
        DynamicCombo API issues that cause frame_idx to be ignored.

        Mode 4a: Keyframes + Lip-sync (audio_url provided)
        Mode 4b: Keyframes + Audio generation (duration provided)

        Args:
            keyframes: List of keyframe dicts with keys:
                - image_name: Uploaded image filename in ComfyUI
                - frame_position: "first", "last", or 0.0-1.0 normalized
                - strength: Guide strength 0.0-1.0 (default 1.0)
            audio_name: Uploaded audio filename (Mode 4a: lip-sync)
            audio_duration: Audio duration in seconds (Mode 4a)
            duration: Target duration in seconds (Mode 4b: audio generation)
            prompt_positive: Positive prompt text
            prompt_negative: Negative prompt text
            seed: Random seed for generation
            width: Video width (must be divisible by 32)
            height: Video height (must be divisible by 32)
            fps: Frames per second (default 30)
            steps: Sampling steps (default 8)
            cfg_scale: CFG scale (default 1.0)
            lora_distilled: Distilled LoRA strength (default 0.6)
            lora_detailer: Detailer LoRA strength (default 1.0)
            lora_camera: Camera LoRA strength (default 0.3)
            img_compression: Image compression level (default 23)
            trim_to_audio: Whether to trim video to audio length (default False)
            frame_alignment: Frame alignment interval for keyframes (default 8)
            buffer_seconds: Extra buffer time beyond input duration (default 1.0s)
            auto_buffer_guide: Buffer guide strategy to prevent flickering (default True):
                - True or "add_node": Add implicit guide node at buffer end (方案 A)
                - "extend_last": Move last keyframe position to buffer end (方案 C)
                - False or "none": Disable buffer guide

        Returns:
            Complete workflow ready for ComfyUI execution

        Raises:
            ValueError: If keyframes is empty or exceeds MAX_KEYFRAMES
            RuntimeError: If multiframe template is not loaded
        """
        if self.multiframe_template is None:
            raise RuntimeError("Multiframe template not loaded")

        if not keyframes:
            raise ValueError("At least one keyframe is required")
        if len(keyframes) > self.MAX_KEYFRAMES:
            raise ValueError(f"Maximum {self.MAX_KEYFRAMES} keyframes supported")

        # Determine mode and calculate frames (with buffer)
        is_audio_gen = audio_name is None and duration is not None
        if is_audio_gen:
            # Mode 4b: Audio generation
            total_duration = duration + buffer_seconds
            num_frames = math.ceil(total_duration * fps) + 1
            audio_frames = math.ceil(duration * 25)  # Audio frames without buffer
        else:
            # Mode 4a: Lip-sync with input audio
            total_duration = audio_duration + buffer_seconds
            num_frames = math.ceil(total_duration * fps) + 1
            audio_frames = None

        if num_frames < 30:
            num_frames = 30

        # Start with base template
        workflow = copy.deepcopy(self.multiframe_template)

        # Node ID counter for dynamic nodes (start from 400 to avoid conflicts)
        node_id = 400

        # Create load/resize/preprocess nodes for each keyframe
        keyframe_node_ids = []
        for i, kf in enumerate(keyframes):
            image_name = kf.get("image_name", "")
            frame_position = kf.get("frame_position", "first" if i == 0 else "last")
            strength = kf.get("strength", 1.0)

            # LoadImage node
            load_node_id = str(node_id)
            workflow[load_node_id] = {
                "inputs": {
                    "image": image_name,
                    "upload": "image"
                },
                "class_type": "LoadImage",
                "_meta": {"title": f"Load Keyframe {i+1}"}
            }
            node_id += 1

            # ImageResizeKJv2 node
            resize_node_id = str(node_id)
            workflow[resize_node_id] = {
                "inputs": {
                    "image": [load_node_id, 0],
                    "width": width,
                    "height": height,
                    "upscale_method": "lanczos",
                    "keep_proportion": "pad",
                    "pad_color": "0, 0, 0",
                    "crop_position": "center",
                    "divisible_by": 32
                },
                "class_type": "ImageResizeKJv2",
                "_meta": {"title": f"Resize Keyframe {i+1}"}
            }
            node_id += 1

            # LTXVPreprocess node
            preprocess_node_id = str(node_id)
            workflow[preprocess_node_id] = {
                "inputs": {
                    "image": [resize_node_id, 0],
                    "img_compression": img_compression
                },
                "class_type": "LTXVPreprocess",
                "_meta": {"title": f"Preprocess Keyframe {i+1}"}
            }
            node_id += 1

            # Calculate frame index
            frame_idx = self._calculate_frame_index(frame_position, num_frames, frame_alignment)

            keyframe_node_ids.append({
                "preprocess_node_id": preprocess_node_id,
                "frame_idx": frame_idx,
                "strength": strength
            })

        # ============================================================
        # v59: BUFFER GUIDE STRATEGIES - Prevent flickering in buffer region
        # Strategy A ("add_node"): Add implicit guide node at buffer end
        # Strategy C ("extend_last"): Move last keyframe position to buffer end
        # ============================================================

        # Normalize auto_buffer_guide to strategy string
        if auto_buffer_guide is True or auto_buffer_guide == "add_node":
            buffer_strategy = "add_node"
        elif auto_buffer_guide == "extend_last":
            buffer_strategy = "extend_last"
        else:
            buffer_strategy = "none"

        if buffer_seconds > 0 and buffer_strategy != "none" and len(keyframe_node_ids) > 0:
            # Calculate the buffer end frame position (aligned)
            buffer_end_frame = self._calculate_frame_index("last", num_frames, frame_alignment)

            # Get the last user keyframe
            last_user_kf = keyframe_node_ids[-1]

            # Only apply if last user keyframe isn't already at buffer end
            if last_user_kf["frame_idx"] < buffer_end_frame:
                if buffer_strategy == "add_node":
                    # Strategy A: Add implicit guide node at buffer end
                    implicit_buffer_kf = {
                        "preprocess_node_id": last_user_kf["preprocess_node_id"],  # Reuse same image
                        "frame_idx": buffer_end_frame,
                        "strength": last_user_kf["strength"]  # Reuse same strength
                    }
                    keyframe_node_ids.append(implicit_buffer_kf)
                    print(f"  [v59] Strategy 'add_node': Added implicit guide at frame {buffer_end_frame}")

                elif buffer_strategy == "extend_last":
                    # Strategy C: Move last keyframe position to buffer end (no extra node)
                    original_frame = last_user_kf["frame_idx"]
                    last_user_kf["frame_idx"] = buffer_end_frame
                    print(f"  [v59] Strategy 'extend_last': Moved last keyframe from frame {original_frame} to {buffer_end_frame}")

        # ============================================================
        # KEY DIFFERENCE: Chain individual LTXVAddGuide nodes
        # Instead of LTXVAddGuideMulti, we create separate LTXVAddGuide
        # nodes and chain them together. This ensures frame_idx is
        # correctly passed as a direct parameter, not through DynamicCombo.
        # ============================================================

        # Initial connections from base template nodes:
        # - LTXVConditioning (164): outputs (positive, negative)
        # - EmptyLTXVLatentVideo (162): outputs (latent)
        prev_positive = ["164", 0]  # LTXVConditioning positive output
        prev_negative = ["164", 1]  # LTXVConditioning negative output
        prev_latent = ["162", 0]    # EmptyLTXVLatentVideo output

        # Create chained LTXVAddGuide nodes
        for i, kf_data in enumerate(keyframe_node_ids):
            guide_node_id = str(node_id)
            workflow[guide_node_id] = {
                "inputs": {
                    "image": [kf_data["preprocess_node_id"], 0],
                    "frame_idx": kf_data["frame_idx"],
                    "strength": kf_data["strength"],
                    "positive": prev_positive,
                    "negative": prev_negative,
                    "latent": prev_latent,
                    "vae": ["184", 2]  # CheckpointLoaderSimple VAE output
                },
                "class_type": "LTXVAddGuide",
                "_meta": {"title": f"Guide Keyframe {i+1} (frame {kf_data['frame_idx']})"}
            }

            # Chain: each node's output becomes the next node's input
            prev_positive = [guide_node_id, 0]
            prev_negative = [guide_node_id, 1]
            prev_latent = [guide_node_id, 2]
            node_id += 1

        # Store last guide node outputs for later use
        last_guide_positive = prev_positive
        last_guide_negative = prev_negative
        last_guide_latent = prev_latent

        # Update CFGGuider (153) to use the last guide's conditioning
        workflow["153"]["inputs"]["positive"] = last_guide_positive
        workflow["153"]["inputs"]["negative"] = last_guide_negative

        # Create audio handling nodes based on mode
        if is_audio_gen:
            # Mode 4b: Generate audio with LTXVEmptyLatentAudio
            empty_audio_node_id = str(node_id)
            workflow[empty_audio_node_id] = {
                "inputs": {
                    "frames_number": audio_frames,
                    "frame_rate": 25,
                    "batch_size": 1,
                    "audio_vae": ["171", 0]
                },
                "class_type": "LTXVEmptyLatentAudio",
                "_meta": {"title": "Empty Audio Latent"}
            }
            node_id += 1

            # LTXVConcatAVLatent - combine video and audio latents
            concat_node_id = str(node_id)
            workflow[concat_node_id] = {
                "inputs": {
                    "video_latent": last_guide_latent,  # From last chained guide
                    "audio_latent": [empty_audio_node_id, 0]
                },
                "class_type": "LTXVConcatAVLatent",
                "_meta": {"title": "Concat AV Latent"}
            }
            node_id += 1

            # Audio decode for output
            audio_decode_node_id = str(node_id)
            workflow[audio_decode_node_id] = {
                "inputs": {
                    "samples": ["245", 1],  # Audio from LTXVSeparateAVLatent
                    "audio_vae": ["171", 0]
                },
                "class_type": "LTXVAudioVAEDecode",
                "_meta": {"title": "Audio VAE Decode"}
            }
            node_id += 1

            audio_output_ref = [audio_decode_node_id, 0]

        else:
            # Mode 4a: Use input audio
            # LoadAudio node
            load_audio_node_id = str(node_id)
            workflow[load_audio_node_id] = {
                "inputs": {
                    "audio": audio_name
                },
                "class_type": "LoadAudio",
                "_meta": {"title": "Load Audio"}
            }
            node_id += 1

            # TrimAudioDuration node
            trim_audio_node_id = str(node_id)
            workflow[trim_audio_node_id] = {
                "inputs": {
                    "audio": [load_audio_node_id, 0],
                    "max_duration": audio_duration,
                    "duration": audio_duration,
                    "start_index": 0
                },
                "class_type": "TrimAudioDuration",
                "_meta": {"title": "Trim Audio"}
            }
            node_id += 1

            # Audio VAE Encode
            audio_encode_node_id = str(node_id)
            workflow[audio_encode_node_id] = {
                "inputs": {
                    "audio": [trim_audio_node_id, 0],
                    "audio_vae": ["171", 0]
                },
                "class_type": "LTXVAudioVAEEncode",
                "_meta": {"title": "Audio VAE Encode"}
            }
            node_id += 1

            # Audio noise mask
            solid_mask_node_id = str(node_id)
            workflow[solid_mask_node_id] = {
                "inputs": {
                    "value": 0,
                    "width": width,
                    "height": height
                },
                "class_type": "SolidMask",
                "_meta": {"title": "Audio Mask"}
            }
            node_id += 1

            # SetLatentNoiseMask
            set_mask_node_id = str(node_id)
            workflow[set_mask_node_id] = {
                "inputs": {
                    "samples": [audio_encode_node_id, 0],
                    "mask": [solid_mask_node_id, 0]
                },
                "class_type": "SetLatentNoiseMask",
                "_meta": {"title": "Set Noise Mask"}
            }
            node_id += 1

            # LTXVConcatAVLatent - combine video and audio latents
            concat_node_id = str(node_id)
            workflow[concat_node_id] = {
                "inputs": {
                    "video_latent": last_guide_latent,  # From last chained guide
                    "audio_latent": [set_mask_node_id, 0]
                },
                "class_type": "LTXVConcatAVLatent",
                "_meta": {"title": "Concat AV Latent"}
            }
            node_id += 1

            audio_output_ref = [trim_audio_node_id, 0]

        # Add SamplerCustomAdvanced node
        sampler_node_id = "161"
        workflow[sampler_node_id] = {
            "inputs": {
                "noise": ["178", 0],
                "guider": ["153", 0],
                "sampler": ["154", 0],
                "sigmas": ["238", 0],
                "latent_image": [concat_node_id, 0]
            },
            "class_type": "SamplerCustomAdvanced",
            "_meta": {"title": "Sampler"}
        }

        # Add VHS_VideoCombine output node
        video_output_node_id = "190"
        workflow[video_output_node_id] = {
            "inputs": {
                "frame_rate": fps,
                "loop_count": 0,
                "filename_prefix": "ltx2_multiframe_chained",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": 19,
                "save_metadata": True,
                "trim_to_audio": trim_to_audio,
                "pingpong": False,
                "save_output": True,
                "images": ["234", 0],
                "audio": audio_output_ref
            },
            "class_type": "VHS_VideoCombine",
            "_meta": {"title": "Video Output"}
        }

        # Inject remaining parameters
        params = {
            "WIDTH": width,
            "HEIGHT": height,
            "NUM_FRAMES": num_frames,
            "FPS": fps,
            "PROMPT_POSITIVE": prompt_positive,
            "PROMPT_NEGATIVE": prompt_negative,
            "SEED": seed,
            "STEPS": steps,
            "CFG_SCALE": cfg_scale,
            "LORA_DISTILLED_STRENGTH": lora_distilled,
            "LORA_DETAILER_STRENGTH": lora_detailer,
            "LORA_CAMERA_STRENGTH": lora_camera,
            "LORA_I2V_STRENGTH": lora_i2v,
        }

        workflow = self._inject_parameters(workflow, params)

        # Remove LoRA nodes with strength=0 to save GPU memory and compute
        workflow = self._remove_zero_strength_loras(workflow)

        return workflow
