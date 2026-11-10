import sys

if __name__ == "__main__":
    if sys.argv[1:2] == ["--drums-component"]:
        from drum_transcriber.__main__ import main
        main(sys.argv[2:])
    else:
        from track2stem_engine.worker import main
        main()
