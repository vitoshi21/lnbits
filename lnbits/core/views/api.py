from flask import g, jsonify, request

from lnbits.bolt11 import decode as bolt11_decode
from lnbits.core import core_app
from lnbits.decorators import api_check_wallet_macaroon, api_validate_post_request
from lnbits.helpers import Status
from lnbits.settings import WALLET

from ..utils import create_invoice, pay_invoice


@core_app.route("/api/v1/payments", methods=["GET"])
@api_check_wallet_macaroon(key_type="invoice")
def api_payments():
    if "check_pending" in request.args:
        for payment in g.wallet.get_payments(include_all_pending=True):
            if payment.is_out:
                payment.set_pending(WALLET.get_payment_status(payment.checking_id).pending)
            elif payment.is_in:
                payment.set_pending(WALLET.get_invoice_status(payment.checking_id).pending)

    return jsonify(g.wallet.get_payments()), Status.OK


@api_check_wallet_macaroon(key_type="invoice")
@api_validate_post_request(
    schema={
        "amount": {"type": "integer", "min": 1, "required": True},
        "memo": {"type": "string", "empty": False, "required": True},
    }
)
def api_payments_create_invoice():
    try:
        checking_id, payment_request = create_invoice(
            wallet_id=g.wallet.id, amount=g.data["amount"], memo=g.data["memo"]
        )
    except Exception as e:
        return jsonify({"message": str(e)}), Status.INTERNAL_SERVER_ERROR

    return jsonify({"checking_id": checking_id, "payment_request": payment_request}), Status.CREATED


@api_check_wallet_macaroon(key_type="admin")
@api_validate_post_request(schema={"bolt11": {"type": "string", "empty": False, "required": True}})
def api_payments_pay_invoice():
    try:
        invoice = bolt11_decode(g.data["bolt11"])

        if invoice.amount_msat == 0:
            return jsonify({"message": "Amountless invoices not supported."}), Status.BAD_REQUEST

        if invoice.amount_msat > g.wallet.balance_msat:
            return jsonify({"message": "Insufficient balance."}), Status.FORBIDDEN

        checking_id = pay_invoice(wallet_id=g.wallet.id, bolt11=g.data["bolt11"])

    except Exception as e:
        return jsonify({"message": str(e)}), Status.INTERNAL_SERVER_ERROR

    return jsonify({"checking_id": checking_id}), Status.CREATED


@core_app.route("/api/v1/payments", methods=["POST"])
@api_validate_post_request(schema={"out": {"type": "boolean", "required": True}})
def api_payments_create():
    if g.data["out"] is True:
        return api_payments_pay_invoice()
    return api_payments_create_invoice()


@core_app.route("/api/v1/payments/<checking_id>", methods=["GET"])
@api_check_wallet_macaroon(key_type="invoice")
def api_payment(checking_id):
    payment = g.wallet.get_payment(checking_id)

    if not payment:
        return jsonify({"message": "Payment does not exist."}), Status.NOT_FOUND
    elif not payment.pending:
        return jsonify({"paid": True}), Status.OK

    try:
        if payment.is_out:
            is_paid = WALLET.get_payment_status(checking_id).paid
        elif payment.is_in:
            is_paid = WALLET.get_invoice_status(checking_id).paid
    except Exception:
        return jsonify({"paid": False}), Status.OK

    if is_paid is True:
        payment.set_pending(False)
        return jsonify({"paid": True}), Status.OK

    return jsonify({"paid": False}), Status.OK