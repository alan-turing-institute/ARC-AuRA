import jsonargparse


def main(**args):
    pass


if __name__ == "__main__":
    parser = jsonargparse.ArgumentParser()
    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="Model name as configured in the LiteLLM gateway.",
    )
    parser.add_argument("--prompt", type=str, required=True, help="Full task prompt.")
    args = parser.parse_args()
    main(args=args)
