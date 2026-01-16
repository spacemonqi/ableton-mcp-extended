# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import json
import logging
import os
import time
import fcntl
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Union

import requests

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

ROUTER_API_BASE = os.environ.get("ROUTER_API_BASE", "http://localhost:9090")


def _router_request(method: str, path: str, payload: Dict[str, Any] = None) -> Dict[str, Any]:
    url = f"{ROUTER_API_BASE}{path}"
    response = requests.request(method, url, json=payload, timeout=15.0)
    if not response.ok:
        raise Exception(f"Router error: {response.text}")
    return response.json()

@dataclass
class AbletonConnection:
    base_url: str
    
    def connect(self) -> bool:
        """Router is the single Ableton gateway; nothing to connect here."""
            return True
    
    def disconnect(self):
        """No-op for HTTP-based router client."""
        return

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Forward a command to the Smart Router (single Ableton gateway)."""
        try:
            payload = {"type": command_type, "params": params or {}}
            response = requests.post(
                f"{self.base_url}/api/ableton/command",
                json=payload,
                timeout=15.0
            )
            if not response.ok:
                raise Exception(f"Router error: {response.text}")
            data = response.json()
            if data.get("status") != "ok":
                raise Exception(data.get("message", "Unknown router error"))
            return data.get("result", {})
        except Exception as e:
            raise Exception(f"Communication error with Router: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        
        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")
        
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
try:
mcp = FastMCP(
    "AbletonMCP",
    description="Ableton Live integration through the Model Context Protocol",
    lifespan=server_lifespan
)
except TypeError:
    # Older MCP SDK versions don't accept "description"
    mcp = FastMCP(
        "AbletonMCP",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAPPINGS_CONFIG_PATH = os.path.join(PROJECT_ROOT, "smart_router", "mappings.json")
STREAMS_CACHE_PATH = os.path.join(PROJECT_ROOT, "smart_router", "streams.json")
LAST_SELECTED_CACHE_PATH = os.path.join(PROJECT_ROOT, "smart_router", "last_selected.json")


def _ensure_mappings_file():
    if not os.path.exists(MAPPINGS_CONFIG_PATH):
        os.makedirs(os.path.dirname(MAPPINGS_CONFIG_PATH), exist_ok=True)
        with open(MAPPINGS_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"settings": {}, "mappings": []}, f, indent=2)


def _locked_read_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
            try:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        except Exception:
            pass
        try:
            return json.load(f)
        except Exception:
            return {}
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _locked_write_json(path: str, data: Dict[str, Any]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass

def get_ableton_connection():
    """Get or create a persistent Router client (single Ableton gateway)."""
    global _ableton_connection

    if _ableton_connection is not None:
        return _ableton_connection

    logger.info("Initializing Router client for Ableton commands")
    _ableton_connection = AbletonConnection(base_url=ROUTER_API_BASE)
    return _ableton_connection


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"

@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.
    
    Parameters:
    - track_index: The index of the track to get information about
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_info", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.
    
    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.
    
    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_name", {"track_index": track_index, "name": name})
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.
    
    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_clip", {
            "track_index": track_index, 
            "clip_index": clip_index, 
            "length": length
        })
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
def add_notes_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes
        })
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.
    
    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_tempo", {"tempo": tempo})
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.
    
    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri
        })
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
            else:
                devices = result.get("devices_after", [])
                return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
        else:
            return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"

@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.
    
    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.
    
    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })
        
        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.
    
    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"

# Device Parameter Control

@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Get all parameters for a specific device.
    
    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_parameters", {
            "track_index": track_index,
            "device_index": device_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"

@mcp.tool()
def set_device_parameter(ctx: Context, track_index: int, device_index: int, parameter_index: int, value: float) -> str:
    """
    Set a device parameter using normalized value (0.0 to 1.0).
    
    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameter_index: The index of the parameter to set
    - value: Normalized value between 0.0 and 1.0
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_parameter", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "value": value
        })
        return f"Set parameter {parameter_index} to {value}: {json.dumps(result)}"
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"

@mcp.tool()
def batch_set_device_parameters(ctx: Context, track_index: int, device_index: int, parameter_indices: List[int], values: List[float]) -> str:
    """
    Set multiple device parameters at once.
    
    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameter_indices: List of parameter indices to set
    - values: List of normalized values (0.0 to 1.0) corresponding to each parameter
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("batch_set_device_parameters", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter_indices": parameter_indices,
            "values": values
        })
        return f"Updated {len(parameter_indices)} parameters: {json.dumps(result)}"
    except Exception as e:
        logger.error(f"Error batch setting device parameters: {str(e)}")
        return f"Error batch setting device parameters: {str(e)}"

# Track Operations

@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track in the Ableton session.
    
    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {"index": index})
        return f"Created new audio track (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error creating audio track: {str(e)}")
        return f"Error creating audio track: {str(e)}"

@mcp.tool()
def set_track_level(ctx: Context, track_index: int, level: float) -> str:
    """
    Set the volume level of a track.
    
    Parameters:
    - track_index: The index of the track
    - level: Volume level (0.0 to 1.0, where 0.85 is 0dB)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_level", {
            "track_index": track_index,
            "level": level
        })
        return f"Set track {track_index} level to {level} (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error setting track level: {str(e)}")
        return f"Error setting track level: {str(e)}"

@mcp.tool()
def set_track_pan(ctx: Context, track_index: int, pan: float) -> str:
    """
    Set the pan position of a track.
    
    Parameters:
    - track_index: The index of the track
    - pan: Pan position (-1.0 = full left, 0.0 = center, 1.0 = full right)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_pan", {
            "track_index": track_index,
            "pan": pan
        })
        return f"Set track {track_index} pan to {pan} (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error setting track pan: {str(e)}")
        return f"Error setting track pan: {str(e)}"

# Scene Management

@mcp.tool()
def get_scenes_info(ctx: Context) -> str:
    """Get information about all scenes in the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_scenes_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scenes info: {str(e)}")
        return f"Error getting scenes info: {str(e)}"

@mcp.tool()
def create_scene(ctx: Context, index: int = -1) -> str:
    """
    Create a new scene in the Ableton session.
    
    Parameters:
    - index: The index to insert the scene at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_scene", {"index": index})
        return f"Created new scene (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error creating scene: {str(e)}")
        return f"Error creating scene: {str(e)}"

@mcp.tool()
def set_scene_name(ctx: Context, index: int, name: str) -> str:
    """
    Set the name of a scene.
    
    Parameters:
    - index: The index of the scene to rename
    - name: The new name for the scene
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scene_name", {
            "index": index,
            "name": name
        })
        return f"Renamed scene {index} to '{name}' (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error setting scene name: {str(e)}")
        return f"Error setting scene name: {str(e)}"

@mcp.tool()
def delete_scene(ctx: Context, index: int) -> str:
    """
    Delete a scene from the Ableton session.
    
    Parameters:
    - index: The index of the scene to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_scene", {"index": index})
        return f"Deleted scene {index} (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error deleting scene: {str(e)}")
        return f"Error deleting scene: {str(e)}"

@mcp.tool()
def fire_scene(ctx: Context, index: int) -> str:
    """
    Trigger/fire a scene to start playing all clips in it.
    
    Parameters:
    - index: The index of the scene to fire
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_scene", {"index": index})
        return f"Fired scene {index} (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error firing scene: {str(e)}")
        return f"Error firing scene: {str(e)}"

# Advanced MIDI Note Operations

@mcp.tool()
def get_notes_from_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Get all MIDI notes from a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_notes_from_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting notes from clip: {str(e)}")
        return f"Error getting notes from clip: {str(e)}"

@mcp.tool()
def transpose_notes_in_clip(ctx: Context, track_index: int, clip_index: int, semitones: int, 
                           from_time: float = None, to_time: float = None, 
                           from_pitch: int = None, to_pitch: int = None) -> str:
    """
    Transpose MIDI notes in a clip by a specified number of semitones.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - semitones: Number of semitones to transpose (positive or negative)
    - from_time: Optional start time to filter notes
    - to_time: Optional end time to filter notes
    - from_pitch: Optional minimum pitch to filter notes
    - to_pitch: Optional maximum pitch to filter notes
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("transpose_notes_in_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "semitones": semitones,
            "from_time": from_time,
            "to_time": to_time,
            "from_pitch": from_pitch,
            "to_pitch": to_pitch
        })
        return f"Transposed notes by {semitones} semitones (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error transposing notes: {str(e)}")
        return f"Error transposing notes: {str(e)}"

@mcp.tool()
def delete_notes_from_clip(ctx: Context, track_index: int, clip_index: int,
                          from_time: float = None, to_time: float = None,
                          from_pitch: int = None, to_pitch: int = None) -> str:
    """
    Delete MIDI notes from a clip within specified ranges.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - from_time: Optional start time to filter notes
    - to_time: Optional end time to filter notes
    - from_pitch: Optional minimum pitch to filter notes
    - to_pitch: Optional maximum pitch to filter notes
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_notes_from_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "from_time": from_time,
            "to_time": to_time,
            "from_pitch": from_pitch,
            "to_pitch": to_pitch
        })
        return f"Deleted notes from clip (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error deleting notes: {str(e)}")
        return f"Error deleting notes: {str(e)}"

@mcp.tool()
def quantize_notes_in_clip(ctx: Context, track_index: int, clip_index: int, 
                          grid_size: float = 0.25, strength: float = 1.0,
                          from_time: float = None, to_time: float = None,
                          from_pitch: int = None, to_pitch: int = None) -> str:
    """
    Quantize MIDI notes in a clip to a grid.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - grid_size: Grid size in beats (e.g., 0.25 = 16th notes)
    - strength: Quantization strength (0.0 to 1.0)
    - from_time: Optional start time to filter notes
    - to_time: Optional end time to filter notes
    - from_pitch: Optional minimum pitch to filter notes
    - to_pitch: Optional maximum pitch to filter notes
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("quantize_notes_in_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "grid_size": grid_size,
            "strength": strength,
            "from_time": from_time,
            "to_time": to_time,
            "from_pitch": from_pitch,
            "to_pitch": to_pitch
        })
        return f"Quantized notes (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error quantizing notes: {str(e)}")
        return f"Error quantizing notes: {str(e)}"

@mcp.tool()
def randomize_note_timing(ctx: Context, track_index: int, clip_index: int, amount: float = 0.1,
                         from_time: float = None, to_time: float = None,
                         from_pitch: int = None, to_pitch: int = None) -> str:
    """
    Randomize the timing of MIDI notes in a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - amount: Amount of randomization in beats
    - from_time: Optional start time to filter notes
    - to_time: Optional end time to filter notes
    - from_pitch: Optional minimum pitch to filter notes
    - to_pitch: Optional maximum pitch to filter notes
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("randomize_note_timing", {
            "track_index": track_index,
            "clip_index": clip_index,
            "amount": amount,
            "from_time": from_time,
            "to_time": to_time,
            "from_pitch": from_pitch,
            "to_pitch": to_pitch
        })
        return f"Randomized note timing (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error randomizing note timing: {str(e)}")
        return f"Error randomizing note timing: {str(e)}"

@mcp.tool()
def set_note_probability(ctx: Context, track_index: int, clip_index: int, probability: float = 1.0,
                        from_time: float = None, to_time: float = None,
                        from_pitch: int = None, to_pitch: int = None) -> str:
    """
    Set the probability of MIDI notes in a clip (for generative music).
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - probability: Probability value (0.0 to 1.0)
    - from_time: Optional start time to filter notes
    - to_time: Optional end time to filter notes
    - from_pitch: Optional minimum pitch to filter notes
    - to_pitch: Optional maximum pitch to filter notes
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_note_probability", {
            "track_index": track_index,
            "clip_index": clip_index,
            "probability": probability,
            "from_time": from_time,
            "to_time": to_time,
            "from_pitch": from_pitch,
            "to_pitch": to_pitch
        })
        return f"Set note probability (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error setting note probability: {str(e)}")
        return f"Error setting note probability: {str(e)}"

# Clip Operations

@mcp.tool()
def set_clip_loop_parameters(ctx: Context, track_index: int, clip_index: int, 
                            loop_start: float = 0.0, loop_end: float = 4.0, 
                            loop_enabled: bool = True) -> str:
    """
    Set loop parameters for a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - loop_start: Loop start position in beats
    - loop_end: Loop end position in beats
    - loop_enabled: Whether looping is enabled
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_loop_parameters", {
            "track_index": track_index,
            "clip_index": clip_index,
            "loop_start": loop_start,
            "loop_end": loop_end,
            "loop_enabled": loop_enabled
        })
        return f"Set clip loop parameters (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error setting clip loop parameters: {str(e)}")
        return f"Error setting clip loop parameters: {str(e)}"

@mcp.tool()
def set_clip_follow_action(ctx: Context, track_index: int, clip_index: int, 
                          action: str = "stop", target_clip: int = None,
                          chance: float = 1.0, time: float = 1.0) -> str:
    """
    Set follow action for a clip (what happens when clip finishes).
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - action: Follow action type ('stop', 'play', 'next', 'previous', 'first', 'last', 'any', 'other')
    - target_clip: Optional target clip index for certain actions
    - chance: Probability of follow action (0.0 to 1.0)
    - time: Time multiplier for follow action
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_follow_action", {
            "track_index": track_index,
            "clip_index": clip_index,
            "action": action,
            "target_clip": target_clip,
            "chance": chance,
            "time": time
        })
        return f"Set clip follow action (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error setting clip follow action: {str(e)}")
        return f"Error setting clip follow action: {str(e)}"

# Automation/Envelope Operations

@mcp.tool()
def get_clip_envelope(ctx: Context, track_index: int, clip_index: int, 
                     device_index: int, parameter_index: int) -> str:
    """
    Get automation envelope data for a parameter in a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - device_index: The index of the device containing the parameter
    - parameter_index: The index of the parameter
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_envelope", {
            "track_index": track_index,
            "clip_index": clip_index,
            "device_index": device_index,
            "parameter_index": parameter_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip envelope: {str(e)}")
        return f"Error getting clip envelope: {str(e)}"

@mcp.tool()
def add_clip_envelope_point(ctx: Context, track_index: int, clip_index: int,
                           device_index: int, parameter_index: int,
                           time: float, value: float, curve_type: int = 0) -> str:
    """
    Add an automation point to a clip's parameter envelope.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - device_index: The index of the device containing the parameter
    - parameter_index: The index of the parameter
    - time: Time position in beats
    - value: Normalized value (0.0 to 1.0)
    - curve_type: Curve type (0 = linear, 1 = ease-in, 2 = ease-out, etc.)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_clip_envelope_point", {
            "track_index": track_index,
            "clip_index": clip_index,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "time": time,
            "value": value,
            "curve_type": curve_type
        })
        return f"Added envelope point (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error adding envelope point: {str(e)}")
        return f"Error adding envelope point: {str(e)}"

@mcp.tool()
def clear_clip_envelope(ctx: Context, track_index: int, clip_index: int,
                       device_index: int, parameter_index: int) -> str:
    """
    Clear all automation points from a clip's parameter envelope.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - device_index: The index of the device containing the parameter
    - parameter_index: The index of the parameter
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("clear_clip_envelope", {
            "track_index": track_index,
            "clip_index": clip_index,
            "device_index": device_index,
            "parameter_index": parameter_index
        })
        return f"Cleared envelope (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error clearing envelope: {str(e)}")
        return f"Error clearing envelope: {str(e)}"

# Audio Import

@mcp.tool()
def import_audio_file(ctx: Context, uri: str, track_index: int = -1, 
                     clip_index: int = 0, create_track_if_needed: bool = True) -> str:
    """
    Import an audio file into a track or clip slot.
    
    Parameters:
    - uri: File path or URI of the audio file to import
    - track_index: The index of the track to import into (-1 = new track)
    - clip_index: The index of the clip slot to import into
    - create_track_if_needed: Whether to create a new track if needed
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("import_audio_file", {
            "uri": uri,
            "track_index": track_index,
            "clip_index": clip_index,
            "create_track_if_needed": create_track_if_needed
        })
        return f"Imported audio file (placeholder): {result}"
    except Exception as e:
        logger.error(f"Error importing audio file: {str(e)}")
        return f"Error importing audio file: {str(e)}"

# Device Introspection / Diagnostic

@mcp.tool()
def introspect_device(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Deep inspection of a device's internal API properties and methods.
    Reveals all accessible attributes, useful for discovering hidden functionality.
    
    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("introspect_device", {
            "track_index": track_index,
            "device_index": device_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error introspecting device: {str(e)}")
        return f"Error introspecting device: {str(e)}"

@mcp.tool()
def get_device_banks(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Get all parameter banks from a device (useful for Max for Live devices).
    Banks may reveal hidden parameters or mapping configurations.
    
    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_banks", {
            "track_index": track_index,
            "device_index": device_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device banks: {str(e)}")
        return f"Error getting device banks: {str(e)}"

# Parameter Selection Detection

@mcp.tool()
def get_last_selected_parameter(ctx: Context) -> str:
    """
    Get the MOST RECENT clicked item in Ableton Live.
    Returns only the single most recently selected element to avoid ambiguity.
    
    Returns a dictionary with:
    - type: One of 'clip', 'parameter', or None
    - data: The selected item's details (name, index, value, etc.)
    - timestamp: When it was selected
    
    Only tracks clip and parameter selections (ignores track/scene to avoid
    cascading selection ambiguity). This is essential for click-to-map workflows.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_last_selected_parameter")
        try:
            _locked_write_json(LAST_SELECTED_CACHE_PATH, result)
        except Exception as cache_error:
            logger.warning(f"Could not write last selected cache: {cache_error}")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting last selected items: {str(e)}")
        return f"Error getting last selected items: {str(e)}"

# Mapping Management Tools

def _load_mappings_config() -> Dict[str, Any]:
    _ensure_mappings_file()
    config = _locked_read_json(MAPPINGS_CONFIG_PATH)
    if "settings" not in config:
        config["settings"] = {}
    if "mappings" not in config or not isinstance(config["mappings"], list):
        config["mappings"] = []
    return config


def _save_mappings_config(config: Dict[str, Any]):
    _locked_write_json(MAPPINGS_CONFIG_PATH, config)


def _build_mapping(
    motion_stream: str,
    track_index: int,
    device_index: int,
    parameter_index: int,
    range_min: float = 0.0,
    range_max: float = 1.0,
    smoothing: float = 0.0,
    enabled: bool = True
) -> Dict[str, Any]:
    return {
        "motion_stream": motion_stream,
        "target": {
            "track_index": int(track_index),
            "device_index": int(device_index),
            "parameter_index": int(parameter_index)
        },
        "range": [float(range_min), float(range_max)],
        "smoothing": float(smoothing),
        "enabled": bool(enabled),
        "updated_at": time.time()
    }


@mcp.tool()
def create_mapping(
    ctx: Context,
    motion_stream: str,
    track_index: int,
    device_index: int,
    parameter_index: int,
    range_min: float = 0.0,
    range_max: float = 1.0,
    smoothing: float = 0.0,
    enabled: bool = True
) -> str:
    try:
        payload = {
            "motion_stream": motion_stream,
            "track_index": track_index,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "range_min": range_min,
            "range_max": range_max,
            "smoothing": smoothing,
            "enabled": enabled
        }
        response = _router_request("POST", "/api/mappings", payload)
        return json.dumps(response.get("mapping", response), indent=2)
    except Exception as e:
        logger.error(f"Error creating mapping: {str(e)}")
        return f"Error creating mapping: {str(e)}"


@mcp.tool()
def create_mapping_from_last_param(
    ctx: Context,
    motion_stream: str,
    range_min: float = 0.0,
    range_max: float = 1.0,
    smoothing: float = 0.0,
    enabled: bool = True
) -> str:
    """
    Create a mapping using the last selected Ableton parameter.

    Parameters:
    - motion_stream: The motion stream name to map from
    - range_min: Output range minimum (default: 0.0)
    - range_max: Output range maximum (default: 1.0)
    - smoothing: Smoothing factor (0-1)
    - enabled: Whether mapping is enabled
    """
    try:
        payload = {
            "motion_stream": motion_stream,
            "range_min": range_min,
            "range_max": range_max,
            "smoothing": smoothing,
            "enabled": enabled
        }
        response = _router_request("POST", "/api/mappings/create-from-last", payload)
        return json.dumps(response.get("mapping", response), indent=2)
    except Exception as e:
        logger.error(f"Error creating mapping from last param: {str(e)}")
        return f"Error creating mapping from last param: {str(e)}"


@mcp.tool()
def update_mapping(
    ctx: Context,
    motion_stream: str,
    track_index: int = None,
    device_index: int = None,
    parameter_index: int = None,
    range_min: float = None,
    range_max: float = None,
    smoothing: float = None,
    enabled: bool = None
) -> str:
    try:
        payload: Dict[str, Any] = {}
        if track_index is not None:
            payload["track_index"] = track_index
        if device_index is not None:
            payload["device_index"] = device_index
        if parameter_index is not None:
            payload["parameter_index"] = parameter_index
        if range_min is not None:
            payload["range_min"] = range_min
        if range_max is not None:
            payload["range_max"] = range_max
        if smoothing is not None:
            payload["smoothing"] = smoothing
        if enabled is not None:
            payload["enabled"] = enabled
        response = _router_request("PUT", f"/api/mappings/{motion_stream}", payload)
        return json.dumps(response.get("mapping", response), indent=2)
    except Exception as e:
        logger.error(f"Error updating mapping: {str(e)}")
        return f"Error updating mapping: {str(e)}"


@mcp.tool()
def delete_mapping(ctx: Context, motion_stream: str) -> str:
    try:
        _router_request("DELETE", f"/api/mappings/{motion_stream}")
        return f"Deleted mapping for '{motion_stream}'."
    except Exception as e:
        logger.error(f"Error deleting mapping: {str(e)}")
        return f"Error deleting mapping: {str(e)}"


@mcp.tool()
def list_mappings(ctx: Context) -> str:
    try:
        response = _router_request("GET", "/api/mappings")
        return json.dumps(response.get("mappings", response), indent=2)
    except Exception as e:
        logger.error(f"Error listing mappings: {str(e)}")
        return f"Error listing mappings: {str(e)}"


@mcp.tool()
def list_discovered_motion_streams(ctx: Context) -> str:
    try:
        data = _router_request("GET", "/api/streams")
        return json.dumps(data, indent=2)
    except Exception as e:
        logger.error(f"Error listing motion streams: {str(e)}")
        return f"Error listing motion streams: {str(e)}"

@mcp.tool()
def observe_mcp_state(ctx: Context) -> str:
    """
    Return Smart Router state for LLM observability.
    Includes streams, mappings (with range/smoothing/enabled/target_meta), and last_selected.
    """
    try:
        data = _router_request("GET", "/api/observe")
        return json.dumps(data, indent=2)
    except Exception as e:
        logger.error(f"Error observing MCP state: {str(e)}")
        return f"Error observing MCP state: {str(e)}"

# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()