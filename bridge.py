from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from flask_pymongo import PyMongo
from web3 import Web3, Account
from web3.middleware import geth_poa_middleware
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv(".env")


app = Flask(__name__)
CORS(app)

# MongoDB Configuration
app.config["MONGO_URI"] = os.environ.get("MONGODB_URI") + "?retryWrites=true&w=majority"
mongo = PyMongo(app)

with open("EURT.json", "r") as f:
    eurt_abi = json.load(f)
with open("RMN.json", "r") as f:
    rmn_abi = json.load(f)

# Define environment variables
CG_API = os.environ.get("COINGECKO_API")
WEB3_INFURA_PROJECT_ID = os.environ.get("WEB3_INFURA_PROJECT_ID")
PRIVATE_KEY = os.environ.get("PRIVATE_KEY")
PRIVATE_KEY_TESTING = os.environ.get("PRIVATE_KEY_TESTING")
TYPE = os.environ.get("type")
EURT_ETH_CONTRACT = os.environ.get("ETH_EURT_CONTRACT_ADDRESS")
BINANCE_USDT_CONTRACT = os.environ.get("BSC_USDT_CONTRACT_ADDRESS")
EURT_SEPOLIA_CONTRACT = os.environ.get("SEPOLIA_USDT_CONTRACT_ADDRESS")
USDT_CONTRACT_ADDRESSES = {
    "Ethereum": os.environ.get("ETH_USDT_CONTRACT_ADDRESS"),
    "Sepolia": os.environ.get("SEPOLIA_USDT_CONTRACT_ADDRESS"),
    "Mantle": os.environ.get("MANTLE_USDT_CONTRACT_ADDRESS"),
    "Binance Smart Chain": os.environ.get("BSC_USDT_CONTRACT_ADDRESS"),
    "Polygon": os.environ.get("POLYGON_USDT_CONTRACT_ADDRESS"),
}
RMN_CONTRACT_ADDRESS_TESTNET = os.environ.get("RMN_CONTRACT_ADDRESS_TESTNET")
RMN_CONTRACT_ADDRESS = os.environ.get("RMN_CONTRACT_ADDRESS")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN")
# ALLOWED_DOMAIN="127.0.0.1"
# ALLOWED_DOMAIN = "https://maalbridge.netlify.app"
TARGET_ADDRESS_TESTNET = os.environ.get("TARGET_ADDRESS_TESTNET")
TARGET_ADDRESS = os.environ.get("TARGET_ADDRESS")
eurt_price = 1.085


# @app.before_request
# def limit_remote_addr():
#     if request.remote_addr != ALLOWED_DOMAIN:
#         abort(403)  # Forbidden


@app.route("/", methods=["GET"])
def status_check():
    return jsonify({"Status": "Live"}), 200


@app.route("/transfer", methods=["POST"])
def handle_transfer():
    auth_token = request.headers.get("Authorization")
    if not auth_token or auth_token != f"Bearer {AUTH_TOKEN}":
        return jsonify({"error": "Unauthorized - Wrong Auth token"}), 401

    data = request.json

    # Check if the txHash has been processed already
    tx_entry = mongo.db.transactions.find_one({"txHash": data["txHash"]})
    if tx_entry:
        if tx_entry.get("processed", False):
            return (
                jsonify({"error": "This transaction has already been processed"}),
                400,
            )
    else:
        # Store the post request data in the database
        mongo.db.transactions.insert_one(
            {
                "txHash": data["txHash"],
                "from": data["from"],
                "to": data["to"],
                "network": data["network"],
                "processed": False,
            }
        )

    # Check if the "to" address matches the specified TARGET_ADDRESS
    if data.get("to") != TARGET_ADDRESS:
        return (
            jsonify(
                {
                    "error": "Invalid target address. Should deposit Asset to {TARGET_ADDRESS}"
                }
            ),
            400,
        )

    # Connect to the specified network
    global w3
    network = data["network"]
    if data["network"] == "Ethereum":
        w3 = Web3(
            Web3.HTTPProvider(f"https://mainnet.infura.io/v3/{WEB3_INFURA_PROJECT_ID}")
        )
    elif data["network"] == "Sepolia":
        w3 = Web3(Web3.HTTPProvider(f"https://eth-sepolia.public.blastapi.io"))
    elif data["network"] == "Mantle":
        w3 = Web3(Web3.HTTPProvider("https://rpc.testnet.mantle.xyz"))
    elif data["network"] == "Binance Smart Chain":
        w3 = Web3(Web3.HTTPProvider("https://binance.llamarpc.com"))
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)  # Middleware for BSC
    elif data["network"] == "Polygon":
        w3 = Web3(Web3.HTTPProvider("https://rpc-mainnet.matic.network"))
        w3.middleware_onion.inject(
            geth_poa_middleware, layer=0
        )  # Middleware for Polygon
    elif data["network"] == "MaalChain Testnet":
        w3 = Web3(Web3.HTTPProvider("https://node1.maalscan.io"))
        w3.middleware_onion.inject(
            geth_poa_middleware, layer=0
        )  # Middleware for MaalChain
    elif data["network"] == "MaalChain":
        w3 = Web3(Web3.HTTPProvider("https://node1-mainnet.maalscan.io"))
        w3.middleware_onion.inject(
            geth_poa_middleware, layer=0
        )  # Middleware for Polygon
    else:
        return jsonify({"error": "Invalid network"}), 400

    # Check transaction
    tx_receipt = w3.eth.get_transaction_receipt(data["txHash"])
    if not tx_receipt:
        return jsonify({"error": "Invalid txHash"}), 400

    if data["network"] == "Binance Smart Chain":
        # Check EURT transfer value in the transaction
        usdt_contract = w3.eth.contract(address=BINANCE_USDT_CONTRACT, abi=eurt_abi)
        token_transfer = usdt_contract.events.Transfer().process_receipt(tx_receipt)

        if not token_transfer or len(token_transfer) == 0:
            return jsonify({"error": "No USDT transfer found in the transaction"}), 400

    if data["network"] == "MaalChain":
        # Check RMN transfer value in the transaction
        rmn_contract = w3.eth.contract(address=RMN_CONTRACT_ADDRESS, abi=rmn_abi)
        token_transfer = rmn_contract.events.Transfer().process_receipt(tx_receipt)

        if not token_transfer or len(token_transfer) == 0:
            return jsonify({"error": "No RMN transfer found in the transaction"}), 400

    # Check if the "from" address in the token transfer matches the "from" address provided in the query
    if token_transfer[0]["args"]["from"] != data["from"]:
        return (
            jsonify(
                {
                    "error": "Mismatch between query 'from' address and transaction 'from' address"
                }
            ),
            400,
        )

    # Check if the Asset was transferred to the target address specified in the POST query
    if token_transfer[0]["args"]["to"] != TARGET_ADDRESS:
        return (
            jsonify(
                {
                    "error": "Asset was not transferred to the specified target address in the query"
                }
            ),
            400,
        )

    token_amount = token_transfer[0]["args"]["value"]

    # euro_price_url = "https://pro-api.coingecko.com/api/v3/simple/price?ids=tether-eurt&vs_currencies=usd&x_cg_pro_api_key=" + "CG_API"
    # # Make a GET request to the API
    # response = requests.get(euro_price_url)

    # # Check if the request was successful
    # if response.status_code == 200:
    #     data = response.json()
    #     # Extract the price
    #     eurt_price_fetch = data["tether-eurt"]["usd"]
    #     eurt_price = eurt_price_fetch
    # else:
    #     print(f"Failed to fetch EURT price: HTTP {response.status_code}")
    #     # Handle the error appropriately (e.g., retry the request, use a default value, or abort the operation)

    # # Now, check if eurt_price has been set
    # if eurt_price is None:
    #     # Handle the case where eurt_price could not be fetched
    #     return jsonify({"error": "Unable to fetch EURT price"}), 500

    # Calculate tokens to send
    transfer_amount = token_amount
    # Account derivation from private key
    account = Account.from_key(PRIVATE_KEY)
    address = account.address

    if data["network"] == "MaalChain":
        # Switch to Ethereum Chain for EURT Transfer
        # w3 = Web3(Web3.HTTPProvider("https://eth-sepolia.public.blastapi.io"))

        # Switch to your custom EVM chain for RMN transfer
        w3 = Web3(Web3.HTTPProvider("https://bsc-dataseed.binance.org"))
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        # Create a contract instance for USDT using the w3_custom instance
        eurt_contract = w3.eth.contract(address=BINANCE_USDT_CONTRACT, abi=eurt_abi)

        # Get the nonce for the transaction
        nonce = w3.eth.get_transaction_count(address)

        # Get the current gas price from the network
        # current_gas_price = w3.eth.gasPrice

        # Build the transfer function for the XAUS token transfer
        transfer_function = eurt_contract.functions.transfer(
            data.get("from"), int(transfer_amount)
        )
        # Build the transfer function for the XAUS token transfer
        txn_parameters = {
            "chainId": 56,
            "gas": 210000,
            "gasPrice": w3.to_wei("4", "gwei"),
            "nonce": nonce,
            "value": 0,  # for ERC20 transfer, value is 0
        }

        usdt_amount_to_transfer = transfer_amount * eurt_price

        txn_data = eurt_contract.functions.transfer(
            data.get("from"), int(usdt_amount_to_transfer)
        ).build_transaction(txn_parameters)
        signed_txn = w3.eth.account.sign_transaction(txn_data, PRIVATE_KEY)
        tx_sent = w3.eth.send_raw_transaction(signed_txn.rawTransaction)

        # After successfully transferring USDT, update the database
        mongo.db.transactions.update_one(
            {"txHash": data["txHash"]},
            {
                "$set": {
                    "processed": True,
                    "ReceiptHash": tx_sent.hex(),
                    "sentRMN": str(token_amount),
                    "receivedUSDT": str(usdt_amount_to_transfer),
                }
            },
        )

        return jsonify(
            {"message": "USDT transfer successful", "USDTTransferTxHash": tx_sent.hex()}
        )

    if data["network"] == "Binance Smart Chain":
        # Switch to your custom EVM chain for RMN transfer
        w3 = Web3(Web3.HTTPProvider("https://node1-mainnet.maalscan.io"))
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        # Create a contract instance for XAUS using the w3_custom instance
        rmn_contract = w3.eth.contract(address=RMN_CONTRACT_ADDRESS, abi=rmn_abi)

        # Get the nonce for the transaction
        nonce = w3.eth.get_transaction_count(address)

        # Get the current gas price from the network
        # current_gas_price = w3.eth.gasPrice

        # Build the transfer function for the XAUS token transfer
        transfer_function = rmn_contract.functions.transfer(
            data.get("from"), int(transfer_amount)
        )
        # Build the transfer function for the XAUS token transfer
        txn_parameters = {
            "chainId": 786,
            "gas": 210000,
            "gasPrice": w3.to_wei("15", "gwei"),
            "nonce": nonce,
            "value": 0,  # for ERC20 transfer, value is 0
        }

        rmn_transfer_amount = transfer_amount / eurt_price

        txn_data = rmn_contract.functions.transfer(
            data.get("from"), int(rmn_transfer_amount)
        ).build_transaction(txn_parameters)
        signed_txn = w3.eth.account.sign_transaction(txn_data, PRIVATE_KEY)
        tx_sent = w3.eth.send_raw_transaction(signed_txn.rawTransaction)

        # After successfully transferring XAUS, update the database
        mongo.db.transactions.update_one(
            {"txHash": data["txHash"]},
            {
                "$set": {
                    "processed": True,
                    "ReceiptHash": tx_sent.hex(),
                    "sentUSDT": str(token_amount),
                    "receivedRMN": str(rmn_transfer_amount),
                }
            },
        )

        return jsonify(
            {"message": "RMN transfer successful", "RMNTransferTxHash": tx_sent.hex()}
        )


@app.route("/getTxDetails/<wallet>", methods=["POST"])
def get_tx_details(wallet):
    # Extract page and documentsPerPage from the POST request's body
    data = request.get_json()
    page = data.get("page", 1)
    documentsPerPage = data.get("documentsPerPage", 5)

    # Convert to integer and validate
    try:
        page = int(page)
        documentsPerPage = int(documentsPerPage)
    except ValueError:
        return jsonify({"error": "Invalid pagination parameters"}), 400

    # Ensure page and documentsPerPage are positive
    if page < 1 or documentsPerPage < 1:
        return jsonify({"error": "Pagination parameters must be positive"}), 400

    # Query the database with pagination
    transactions = (
        mongo.db.transactions.find({"from": wallet})
        .sort([("_id", -1)])
        .skip((page - 1) * documentsPerPage)
        .limit(documentsPerPage)
    )

    # Convert each transaction's ObjectId to a string
    transactions_list = []
    for txn in transactions:
        txn["_id"] = str(txn["_id"])  # Convert ObjectId to string
        transactions_list.append(txn)

    return jsonify(transactions_list)


if __name__ == "__main__":
    app.run(debug=True)
