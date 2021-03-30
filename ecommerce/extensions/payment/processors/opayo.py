""" Opayo payment processing. """
import hashlib
import logging

import requests
from django.urls import reverse
from oscar.apps.payment.exceptions import GatewayError
from urllib.parse import urljoin

from ecommerce.core.url_utils import get_ecommerce_url
from ecommerce.extensions.payment.exceptions import InvalidSignatureError
from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse

logger = logging.getLogger(__name__)


class Opayo(BasePaymentProcessor):
    """
    Constructs a new instance of the Opayo processor
    For reference, see https://developer-eu.elavon.com/docs/opayo-server.

    Raises:
        KeyError: If no settings configured for this payment processor.
    """

    NAME = 'opayo'
    version = '4.00'
    test_action = 'https://test.sagepay.com/gateway/service/vspserver-register.vsp'
    live_action = 'https://live.sagepay.com/gateway/service/vspserver-register.vsp'

    def __init__(self, site):
        """
        Constructs a new instance of the Opayo processor.
        """
        super(Opayo, self).__init__(site)
        self.vendor = self.configuration.get('vendor')
        self.mode = self.configuration.get('mode')
        self.action = self.test_action

        if self.mode == 'live':
            self.action = self.live_action

    def get_course_name_title(self, line):
        """
        Get Course name & Title from basket item

        Arguments:
            line: basket item

        Returns:
             Concatenated string containing course name & title if exists.
        """
        course_name = ''
        line_course = line.product.course
        if line_course and line_course.name:
            # The shopping basket content is passed in a colon-deliminated string forming the Basket value.
            course_name = "{}|".format(line_course.name.replace(':', ''))
        return course_name + line.product.title

    def get_transaction_parameters(self, basket, billing_address, request=None, **kwargs):
        return_url = urljoin(get_ecommerce_url(), reverse('opayo:execute'))

        basket_data = '{}'.format(basket.num_lines)
        for line in basket.all_lines():
            basket_data += ':{}'.format(self.get_course_name_title(line))
            basket_data += ':{}'.format(line.quantity)
            basket_data += ':'  # item value without tax
            basket_data += ':'  # tax value
            basket_data += ':{}'.format(str(line.line_price_incl_tax_incl_discounts / line.quantity))
            basket_data += ':{}'.format(str(line.line_price_incl_tax_incl_discounts))

        data = {
            'VPSProtocol': self.version,
            'TxType': 'PAYMENT',
            'Vendor': self.vendor,
            'NotificationURL': return_url,
            'VendorTxCode': basket.order_number,
            'Amount': str(basket.total_incl_tax),
            'Currency': basket.currency,
            'Description': basket.order_number,

            'BillingFirstnames': billing_address['first_name'],
            'BillingSurname': billing_address['last_name'],
            'BillingAddress1': '{} {}'.format(billing_address['address_line1'], billing_address['address_line2']),
            'BillingCity': billing_address['city'],
            'BillingCountry': billing_address['country'],
            'BillingState': billing_address['state'],
            'BillingPostCode': billing_address['postal_code'],

            'DeliveryFirstnames': billing_address['first_name'],
            'DeliverySurname': billing_address['last_name'],
            'DeliveryAddress1': '{} {}'.format(billing_address['address_line1'], billing_address['address_line2']),
            'DeliveryCity': billing_address['city'],
            'DeliveryCountry': billing_address['country'],
            'DeliveryState': billing_address['state'],
            'DeliveryPostCode': billing_address['postal_code'],
            
            'Basket': basket_data
        }

        response = requests.post(self.action, data=data)

        try:
            response.raise_for_status()
        except requests.HTTPError:
            logger.warning(
                'Failed to start Opayo payment. [%s] returned status [%d] with content %s',
                self.action, response.status_code, response.content
            )
            raise GatewayError('Failed to start Opayo payment')

        response_json = {}
        for kv in response.text.splitlines():
            k, v = kv.split('=', 1)
            response_json[k] = v

        if not response_json['Status'] in ['OK', 'OK REPEATED']:
            entry = self.record_processor_response(
                response_json,
                transaction_id=response_json['VPSTxId'],
                basket=basket
            )
            logger.error(
                u"%s [%d], %s [%d].",
                "Failed to create Opayo payment for basket",
                basket.id,
                "Opayo response recorded in entry",
                entry.id,
                exc_info=True
            )
            error = response_json['StatusDetail']
            raise GatewayError(error)

        self.record_processor_response(response_json, transaction_id=response_json['VPSTxId'], basket=basket)
        logger.info("Successfully created Opayo payment [%s] for basket [%d].", response_json['VPSTxId'], basket.id)
        approval_url = response_json['NextURL']
        parameters = {
            'payment_page_url': approval_url,
        }

        return parameters

    @property
    def cancel_url(self):
        return get_ecommerce_url(self.configuration['cancel_checkout_path'])

    @property
    def error_url(self):
        return get_ecommerce_url(self.configuration['error_path'])

    def handle_processor_response(self, response, basket):
        payment_processor_response = basket.paymentprocessorresponse_set.filter(
            response__contains='SecurityKey'
        ).first()
        transaction_id = response.get('VPSTxId', '')
        sign_fields = ['VPSTxId', 'VendorTxCode', 'Status', 'TxAuthNo', 'VendorName', 'AVSCV2',
                       'SecurityKey', 'AddressResult', 'PostCodeResult', 'CV2Result', 'GiftAid',
                       '3DSecureStatus', 'CAVV', 'AddressStatus', 'PayerStatus', 'CardType',
                       'Last4Digits', 'DeclineCode', 'ExpiryDate', 'FraudResponse', 'BankAuthCode',
                       'ACSTransID', 'DSTransID', 'SchemeTraceID']

        sign_string = ''
        for sign_field in sign_fields:
            if sign_field == 'SecurityKey':
                sign_string += payment_processor_response.response.get('SecurityKey', '') if payment_processor_response else ''
            elif sign_field == 'VendorName':
                sign_string += self.vendor
            else:
                sign_string += response.get(sign_field, '')

        sign = hashlib.md5(sign_string.encode('utf-8')).hexdigest()

        if sign != response.get('VPSSignature', '').lower():
            entry = self.record_processor_response(response, transaction_id=transaction_id, basket=basket)
            msg = 'Signatures do not match. Payment data has modified by a third party.' \
                  ' Opayo response was recorded in entry {}.'.format(entry.id)
            logger.exception(msg)
            raise InvalidSignatureError(msg)

        self.record_processor_response(response, transaction_id=transaction_id, basket=basket)
        logger.info("Successfully executed Opayo payment [%s] for basket [%d].", transaction_id, basket.id)

        currency = basket.currency
        total = str(basket.total_incl_tax)
        card_number = response.get('Last4Digits', '')
        card_type = response.get('CardType', '')

        return HandledProcessorResponse(
            transaction_id=transaction_id,
            total=total,
            currency=currency,
            card_number=card_number,
            card_type=card_type
        )

    def issue_credit(self, order_number, basket, reference_number, amount, currency):
        raise NotImplementedError
