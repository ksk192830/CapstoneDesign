from machine_vision_client.video.visible_stream import VisibleStream


def main() -> None:
    stream = VisibleStream()
    try:
        print(f"Opening visible stream from: {stream.url}")
        stream.show()
    except RuntimeError as error:
        print(f"Stream error: {error}")
    finally:
        stream.release()


if __name__ == "__main__":
    main()
