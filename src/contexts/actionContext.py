actions = {
    "click": {
        "description": "Click an element using robust Playwright selectors (role, text, :has-text, CSS, or XPath). Useful for navigation, opening dropdowns, submitting forms, or triggering JS events. Returns true if the element was found and clicked, false otherwise. Never use jQuery-style :contains().",
        "action_structure": {
            "action": "click",
            "selector": "Selector for has-text/css/xpath (e.g., 'a:has-text(\"Next\")', 'button[type=\"submit\"]', '//a[normalize-space()=\"Next\"]').",
        },
        "examples": [
            {
                "action": "click",
                "selector": "a:has-text(\"6\")"
            },
            {
                "action": "click",
                "selector": "button.load-more"
            },
            {
                "action": "click",
                "selector": "//button[normalize-space()='Continue']",
            }
        ],
        "notes": [
            "Use role for links/buttons with accessible names.",
            "For plain text clicks, use text=… or :has-text(\"…\"); do not use :contains().",
            "When multiple elements match, provide nth or add narrowing attributes.",
            "Prefer page-level click with these selector engines over raw CSS-only queries."
        ]
    },
    "enter_text": {
        "description": "Enter text into an input field or textarea. Clears existing content before entering new text. Commonly used for filling out forms, search boxes, or any text input elements. Returns True if element was found and text was entered, False otherwise.",
        "action_structure": {
            "action": "enter_text",
            "selector": "CSS selector for the input element",
            "params": {
                "text": "The text string to enter"
            }
        },
        "example": {
            "action": "enter_text",
            "selector": "input#search",
            "params": {
                "text": "ransomware victims 2024"
            }
        }
    },
    "press_key": {
        "description": "Press a specific keyboard key on a given element. Useful for submitting forms with Enter key, navigating with arrow keys, or triggering keyboard shortcuts. Returns True if element was found and key was pressed, False otherwise.",
        "action_structure": {
            "action": "press_key",
            "selector": "CSS selector for the target element",
            "params": {
                "key": "Key name (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown')"
            }
        },
        "example": {
            "action": "press_key",
            "selector": "input.search-field",
            "params": {
                "key": "Enter"
            }
        }
    },
    "wait": {
        "description": "Wait for an element to appear on the page AND for its HTML content to change. Useful for waiting for dynamic content to load, AJAX responses, or React/Vue components to update. Raises exception if element not found within timeout period.",
        "action_structure": {
            "action": "wait",
            "selector": "CSS selector for the element to wait for",
            "params": {
                "timeout": "Optional: Maximum time to wait in milliseconds (default: 10000)"
            }
        },
        "example": {
            "action": "wait",
            "selector": "div.results-container",
            "params": {
                "timeout": 15000
            }
        },
        "note": "The wait action passes selector as first argument, not in params"
    },
    "scroll_to": {
        "description": "Scroll the page to make an element visible in the viewport. Essential for lazy-loaded content, infinite scroll pages, or elements below the fold. Returns True if element was found and scrolled to, False otherwise.",
        "action_structure": {
            "action": "scroll_to",
            "selector": "CSS selector for the element to scroll to"
        },
        "example": {
            "action": "scroll_to",
            "selector": "footer.pagination"
        }
    },
    "handle_dialog": {
        "description": "Set up a handler to automatically dismiss JavaScript dialog boxes (alert, confirm, prompt). Must be called before the dialog appears. Useful for pages that show popups or confirmation dialogs that would otherwise block automation.",
        "action_structure": {
            "action": "handle_dialog"
        },
        "example": {
            "action": "handle_dialog"
        }
    },
    "scrape_and_store": {
        "description": "Extract all visible text from the current page, intelligently chunk it with 10% overlap, process each chunk through LLM to extract structured ransomware victim data, and store results in MongoDB. Includes deduplication via content hashing to avoid reprocessing identical pages. Uses concurrent processing for efficiency.",
        "action_structure": {
            "action": "scrape_and_store"
        },
        "returns": "True if new entries were extracted and stored, False if page was already processed or no entries found",
        "extracted_fields": [
            "post_title",
            "ransomware_group_name",
            "discovered_timedate",
            "description",
            "industry",
            "published_timedate",
            "post_url",
            "country",
            "ransomeware_activity",
            "company_website",
            "duplicates"
        ],
        "example": {
            "action": "scrape_and_store"
        },
        "note": "This action automatically receives victims_collection, session_collection, and llm from the executor context"
    }
}

from dataclasses import dataclass, field
from typing import Dict, List, Any

@dataclass
class ActionContext:
    """
    Context provider for web scraping actions.
    
    This class maintains the registry of available actions for the agentic web scraper.
    Actions are executed via the execute() method which expects a list of action objects.
    
    Each action object should have the following structure:
    {
        "action": "action_name",
        "selector": "CSS selector" or null,
        "params": {param_name: param_value} or {}
    }
    
    The executor handles special cases:
    - 'wait' action: selector is passed as first argument, not in params
    - 'scrape_and_store': automatically injects victims_collection, session_collection, and llm
    - Actions without selectors: handle_dialog, scrape_and_store
    
    All actions return success/failure status for error handling and flow control.
    """
    actions: Dict[str, Dict[str, Any]] = field(default_factory=lambda: actions)