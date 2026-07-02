import argparse

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Envia um payload local parecido com o webhook da Meta para /webhook/meta."
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhook/meta")
    parser.add_argument("--phone", default="5514999999999")
    parser.add_argument("--message", default="agendar")
    args = parser.parse_args()

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-local",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5514000000000",
                                "phone_number_id": "phone-number-id-local",
                            },
                            "contacts": [{"profile": {"name": "Cliente Local"}, "wa_id": args.phone}],
                            "messages": [
                                {
                                    "from": args.phone,
                                    "id": "wamid.local-smoke-1",
                                    "timestamp": "1719250000",
                                    "type": "text",
                                    "text": {"body": args.message},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    response = httpx.post(args.url, json=payload, timeout=10.0)
    print(f"Status: {response.status_code}")
    print(response.text)


if __name__ == "__main__":
    main()
