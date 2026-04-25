#!/usr/bin/env python3
"""
ContextRelay Engineer Automation Script
======================================
Subscribes to saas-specs channel, automatically downloads files, and sends feedback.
"""

import sys
import json
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'python'))

from contextrelay.client import ContextRelay

CONTEXTRELAY_URL = 'https://contextrelay.your-account.workers.dev'

def process_file(url: str) -> None:
    """Pull context, save file, push feedback."""
    hub = ContextRelay(base_url=CONTEXTRELAY_URL)
    
    print(f"\n[RECEIVED] {url}")
    
    try:
        # Pull the payload
        content = hub.pull(url)
        payload = json.loads(content)
        filename = payload['filename']
        code = payload['code']
        
        # Save the file
        os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
        with open(filename, 'w') as f:
            f.write(code)
        
        print(f"[SAVED] {filename}")
        
        # Push feedback
        feedback = {'status': 'success', 'file': filename}
        feedback_url = hub.push(json.dumps(feedback), channel='saas-feedback')
        print(f"[FEEDBACK] {feedback_url}")
        
    except Exception as e:
        print(f"[ERROR] {url}: {e}")
        feedback = {'status': 'error', 'file': url, 'error': str(e)}
        hub.push(json.dumps(feedback), channel='saas-feedback')


def main():
    hub = ContextRelay(base_url=CONTEXTRELAY_URL)
    print("ContextRelay Engineer Automation")
    print("Subscribed to: saas-specs")
    print("Feedback channel: saas-feedback")
    print("Press Ctrl+C to stop\n")
    
    hub.subscribe(
        channel='saas-specs',
        callback=process_file,
        max_reconnect_delay=60.0
    )


if __name__ == '__main__':
    main()
