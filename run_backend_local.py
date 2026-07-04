import os
import sys

import uvicorn
from dotenv import load_dotenv

if __name__ == '__main__':
    repo_root = os.path.dirname(__file__)
    backend_dir = os.path.join(repo_root, 'backend')
    sys.path.append(backend_dir)

    load_dotenv(os.path.join(backend_dir, '.env'))

    # Local runs should not send real email unless explicitly enabled.
    os.environ.setdefault('EMAIL_DELIVERY_ENABLED', 'false')

    uvicorn.run('app.main:app', host='127.0.0.1', port=8000, reload=False)
