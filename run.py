"""开发环境启动入口：python run.py [--browser]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--wbot-worker':
        from app.script_worker import main
        sys.exit(main(sys.argv[2:]))
    from app.main import main
    sys.exit(main())
