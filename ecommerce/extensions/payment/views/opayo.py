import logging

from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Div, Layout
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from oscar.apps.partner import strategy
from oscar.core.loading import get_class, get_model
from oscar.apps.payment.exceptions import PaymentError

from ecommerce.extensions.basket.admin import PaymentProcessorResponse
from ecommerce.extensions.payment.processors.opayo import Opayo
from ecommerce.extensions.payment.forms import update_basket_queryset_filter, country_choices
from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.checkout.utils import get_receipt_page_url


logger = logging.getLogger(__name__)

Applicator = get_class('offer.applicator', 'Applicator')
Basket = get_model('basket', 'Basket')


class OpayoPaymentForm(forms.Form):
    """
    Payment form with billing details.
    """
    basket = forms.ModelChoiceField(
        queryset=Basket.objects.all(),
        widget=forms.HiddenInput(),
        required=False,
        error_messages={
            'invalid_choice': _('There was a problem retrieving your basket. Refresh the page to try again.'),
        }
    )
    first_name = forms.CharField(
        max_length=20,
        label=_('First Name (required)')
    )
    last_name = forms.CharField(
        max_length=20,
        label=_('Last Name (required)')
    )
    address_line1 = forms.CharField(
        max_length=40,
        label=_('Address (required)')
    )
    address_line2 = forms.CharField(
        max_length=9,
        required=False,
        label=_('Suite/Apartment Number')
    )
    city = forms.CharField(
        max_length=40,
        label=_('City (required)')
    )
    country = forms.ChoiceField(
        choices=country_choices,
        label=_('Country (required)')
    )
    state = forms.CharField(
        max_length=2,
        required=False,
        label=_('State/Province')
    )
    postal_code = forms.CharField(
        max_length=10,
        required=False,
        label=_('Zip/Postal Code')
    )

    def __init__(self, user, request, *args, **kwargs):
        super(OpayoPaymentForm, self).__init__(*args, **kwargs)
        self.request = request
        update_basket_queryset_filter(self, user)

        self.helper = FormHelper(self)
        self.helper.layout = Layout(
            Div('basket'),
            Div(
                Div('first_name'),
                HTML('<p class="help-block"></p>'),
                css_class='form-item col-md-6'
            ),
            Div(
                Div('last_name'),
                HTML('<p class="help-block"></p>'),
                css_class='form-item col-md-6'
            ),
            Div(
                Div('address_line1'),
                HTML('<p class="help-block"></p>'),
                css_class='form-item col-md-6'
            ),
            Div(
                Div('address_line2'),
                HTML('<p class="help-block"></p>'),
                css_class='form-item col-md-6'
            ),
            Div(
                Div('city'),
                HTML('<p class="help-block"></p>'),
                css_class='form-item col-md-6'
            ),
            Div(
                Div('country'),
                HTML('<p class="help-block"></p>'),
                css_class='form-item col-md-6'
            ),
            Div(
                Div('state'),
                HTML('<p class="help-block"></p>'),
                css_class='form-item col-md-6'
            ),
            Div(
                Div('postal_code'),
                HTML('<p class="help-block"></p>'),
                css_class='form-item col-md-6'
            )
        )

    def clean_basket(self):
        basket = self.cleaned_data['basket']

        if basket:
            basket.strategy = self.request.strategy
            Applicator().apply(basket, self.request.user, self.request)

        return basket

    def clean(self):
        cleaned_data = super(OpayoPaymentForm, self).clean()

        # Perform specific validation for the United States and Canada
        country = cleaned_data.get('country')
        if country in ('US', 'CA'):
            state = cleaned_data.get('state')
            postal_code = cleaned_data.get('postal_code')

            if not state:
                raise ValidationError({'state': _('This field is required.')})
            if not postal_code:
                raise ValidationError({'postal_code': _('This field is required.')})


class TransactionRegistrationView(View):
    http_method_names = ['options', 'get', 'post']
    form_class = OpayoPaymentForm

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        logger.info(
            '%s called for basket [%d]. It is in the [%s] state.',
            self.__class__.__name__,
            request.basket.id,
            request.basket.status
        )
        return super(TransactionRegistrationView, self).dispatch(request, *args, **kwargs)

    @property
    def payment_processor(self):
        return Opayo(self.request.site)

    def get(self, request):
        form = self.form_class(
            user=request.user,
            request=request,
            initial={'basket': request.basket},
            label_suffix=''
        )
        form_template = render_to_string('payment/opayo.html', {'opayo_payment_form': form})
        return JsonResponse({'form_template': form_template}, status=200)

    def post(self, request):  # pylint: disable=unused-argument
        form_kwargs = self.get_form_kwargs()
        form = self.form_class(**form_kwargs)

        if form.is_valid():
            return self.checkout(form, request)

        return self.form_invalid(form)

    def get_form_kwargs(self):
        return {
            'data': self.request.POST,
            'user': self.request.user,
            'request': self.request,
        }

    def checkout(self, form, request):
        form_data = form.cleaned_data
        basket = form_data['basket']
        logger.info(
            'Checkout view called for basket [%s].',
            basket.id
        )
        # Freeze the basket so that it cannot be modified
        basket.freeze()

        parameters = self.payment_processor.get_transaction_parameters(
            basket, billing_address=form_data, request=request
        )
        payment_page_url = parameters.get('payment_page_url')

        data = {
            'payment_page_url': payment_page_url,
        }

        return JsonResponse(data, status=200)

    def form_invalid(self, form):
        logger.info(
            'Invalid payment form submitted for basket [%d].',
            self.request.basket.id
        )

        errors = {field: error[0] for field, error in form.errors.items()}
        logger.debug(errors)
        data = {'field_errors': errors}

        if errors.get('basket'):
            data['error'] = _('There was a problem retrieving your basket. Refresh the page to try again.')

        return JsonResponse(data, status=200)


class OpayoPaymentExecutionView(EdxOrderPlacementMixin, View):
    """Execute an approved Opayo payment and place an order for paid products as appropriate."""

    @property
    def payment_processor(self):
        return Opayo(self.request.site)

    # Disable atomicity for the view. Otherwise, we'd be unable to commit to the database
    # until the request had concluded; Django will refuse to commit when an atomic() block
    # is active, since that would break atomicity. Without an order present in the database
    # at the time fulfillment is attempted, asynchronous order fulfillment tasks will fail.
    @method_decorator(transaction.non_atomic_requests)
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(OpayoPaymentExecutionView, self).dispatch(request, *args, **kwargs)

    def _get_basket(self, transaction_id):
        payment_processor_response = PaymentProcessorResponse.objects.filter(
            processor_name=self.payment_processor.NAME,
            transaction_id=transaction_id
        ).first()

        if payment_processor_response:
            basket = payment_processor_response.basket
            basket.strategy = strategy.Default()
            Applicator().apply(basket, basket.owner, self.request)
            return basket
        else:
            logger.exception(u"Unexpected error during basket retrieval while executing Opayo payment.")
            return None

    def post(self, request, *args, **kwargs):
        status = request.POST.get('Status')
        payment_processor = self.payment_processor
        transaction_id = request.POST.get('VPSTxId')
        basket = self._get_basket(transaction_id)

        if not basket:
            redirect_url = self.payment_processor.error_url
            return HttpResponse(
                content=u'Status=INVALID\r\nStatusDetail=Unexpected error during basket retrieval while executing Opayo payment.\r\nRedirectURL={}'.format(redirect_url)
            )

        if status in ['ABORT', 'REJECTED']:
            entry = payment_processor.record_processor_response(
                request.POST, transaction_id=transaction_id, basket=basket
            )
            logger.warning(
                "Transaction is cancelled. Opayo response was recorded in entry [%d].",
                entry.id
            )
            redirect_url = payment_processor.cancel_url
            return HttpResponse(content=u'Status=OK\r\nStatusDetail={}\r\nRedirectURL={}'.format(status, redirect_url))

        elif status == 'OK':
            paypal_response = request.POST.dict()

            try:
                with transaction.atomic():
                    try:
                        self.handle_payment(paypal_response, basket)
                    except PaymentError:
                        redirect_url = self.payment_processor.error_url
                        status_detail = 'Attempts to handle payment for basket {} failed.'.format(basket.id)
                        return HttpResponse(
                            content=u'Status=INVALID\r\nStatusDetail={}\r\nRedirectURL={}'.format(
                                status_detail, redirect_url
                            )
                        )
            except:  # pylint: disable=bare-except
                logger.exception('Attempts to handle payment for basket [%d] failed.', basket.id)
                redirect_url = self.payment_processor.error_url
                status_detail = 'Attempts to handle payment for basket {} failed.'.format(basket.id)
                return HttpResponse(
                    content=u'Status=INVALID\r\nStatusDetail={}\r\nRedirectURL={}'.format(
                        status_detail, redirect_url
                    )
                )

            try:
                order = self.create_order(request, basket)
            except Exception:  # pylint: disable=broad-except
                redirect_url = self.payment_processor.error_url
                status_detail = 'Attempts to handle payment for basket {} failed.'.format(basket.id)
                return HttpResponse(
                    content=u'Status=INVALID\r\nStatusDetail={}\r\nRedirectURL={}'.format(
                        status_detail, redirect_url
                    )
                )

            try:
                self.handle_post_order(order)
            except Exception:  # pylint: disable=broad-except
                self.log_order_placement_exception(basket.order_number, basket.id)

            redirect_url = get_receipt_page_url(
                order_number=basket.order_number,
                site_configuration=basket.site.siteconfiguration,
                disable_back_button=True,
            )
            status_detail = 'Handle payment for basket {} success.'.format(basket.id)
            return HttpResponse(
                content=u'Status=OK\r\nStatusDetail={}\r\nRedirectURL={}'.format(
                    status_detail, redirect_url
                )
            )
        else:
            redirect_url = self.payment_processor.error_url
            entry = payment_processor.record_processor_response(
                request.POST, transaction_id=transaction_id, basket=basket
            )
            logger.warning(
                "The authorisation was failed by the bank. Opayo response was recorded in entry [%d].",
                entry.id
            )
            return HttpResponse(content=u'Status=OK\r\nStatusDetail={}\r\nRedirectURL={}'.format(status, redirect_url))
