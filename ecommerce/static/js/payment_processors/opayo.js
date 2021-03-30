/**
 * Opay payment processor specific actions.
 */
define([
    'jquery',
    'underscore',
    'underscore.string',
    'js-cookie'

], function($, _, _s, Cookies) {
    'use strict';

    return {
        init: function(config) {
            this.transactionRegistrationUrl = config.transactionRegistrationUrl;
            this.$buttonCheck = $('button#opayo');
            this.$containerForm = $('body');
            this.addEventListenerButtonCheck()
        },

        getExtraInfo: function (e) {
            this.$buttonCheck.off('click');
            $.ajax({
                url: this.transactionRegistrationUrl,
                method: 'GET',
                contentType: 'application/json; charset=utf-8',
                dataType: 'json',
                success: this.onSuccess.bind(this),
                error: this.onFail.bind(this)
            });
        },

        onFail: function() {
            this.closeExtraInfo();
            var message = gettext('Problem occurred during checkout. Please contact support.');
            $('#messages').html(_s.sprintf('<div class="alert alert-error">%s</div>', message));
        },

        onSuccess: function (data) {
            $('#opayo-payment-button .fa-spinner').addClass('hidden');
            if (data.form_template) {
                this.$containerForm.append(data.form_template)
                this.onReadyForm();
            } else if (data.field_errors || data.error) {
                this.renderErrors(data);
                this.onReadyForm();
            } else if (data.payment_page_url) {
                window.location.href=data.payment_page_url;
            }
        },

        onReadyForm: function () {
            var self = this,
                $selectCountry = $('#opayo-payment-form select[name=country]');

            $selectCountry.on('change', function() {
                var country = $selectCountry.val(),
                    $inputDiv = $('#opayo-payment-form #div_id_state .controls'),
                    states = {
                        US: {
                            Alabama: 'AL',
                            Alaska: 'AK',
                            American: 'AS',
                            Arizona: 'AZ',
                            Arkansas: 'AR',
                            'Armed Forces Americas': 'AA',
                            'Armed Forces Europe': 'AE',
                            'Armed Forces Pacific': 'AP',
                            California: 'CA',
                            Colorado: 'CO',
                            Connecticut: 'CT',
                            Delaware: 'DE',
                            'Dist. of Columbia': 'DC',
                            Florida: 'FL',
                            Georgia: 'GA',
                            Guam: 'GU',
                            Hawaii: 'HI',
                            Idaho: 'ID',
                            Illinois: 'IL',
                            Indiana: 'IN',
                            Iowa: 'IA',
                            Kansas: 'KS',
                            Kentucky: 'KY',
                            Louisiana: 'LA',
                            Maine: 'ME',
                            Maryland: 'MD',
                            'Marshall Islands': 'MH',
                            Massachusetts: 'MA',
                            Michigan: 'MI',
                            Micronesia: 'FM',
                            Minnesota: 'MN',
                            Mississippi: 'MS',
                            Missouri: 'MO',
                            Montana: 'MT',
                            Nebraska: 'NE',
                            Nevada: 'NV',
                            'New Hampshire': 'NH',
                            'New Jersey': 'NJ',
                            'New Mexico': 'NM',
                            'New York': 'NY',
                            'North Carolina': 'NC',
                            'North Dakota': 'ND',
                            'Northern Marianas': 'MP',
                            Ohio: 'OH',
                            Oklahoma: 'OK',
                            Oregon: 'OR',
                            Palau: 'PW',
                            Pennsylvania: 'PA',
                            'Puerto Rico': 'PR',
                            'Rhode Island': 'RI',
                            'South Carolina': 'SC',
                            'South Dakota': 'SD',
                            Tennessee: 'TN',
                            Texas: 'TX',
                            Utah: 'UT',
                            Vermont: 'VT',
                            Virginia: 'VA',
                            'Virgin Islands': 'VI',
                            Washington: 'WA',
                            'West Virginia': 'WV',
                            Wisconsin: 'WI',
                            Wyoming: 'WY'
                        },
                        CA: {
                            Alberta: 'AB',
                            'British Columbia': 'BC',
                            Manitoba: 'MB',
                            'New Brunswick': 'NB',
                            'Newfoundland and Labrador': 'NL',
                            'Northwest Territories': 'NT',
                            'Nova Scotia': 'NS',
                            Nunavut: 'NU',
                            Ontario: 'ON',
                            'Prince Edward Island': 'PE',
                            Quebec: 'QC',
                            Saskatchewan: 'SK',
                            Yukon: 'YT'
                        }
                    },
                    stateSelector

                if (country === 'US' || country === 'CA') {
                    $($inputDiv).empty();
                    stateSelector = '<select name="state" class="select form-control" id="id_state" aria-required="true" required></select>';
                    $($inputDiv).append(stateSelector);
                    $('#opayo-payment-form #id_state').append(
                      $('<option>', {value: '', text: gettext('<Choose state/province>')})
                    );
                    $('#opayo-payment-form #div_id_state').find('label').html(
                      gettext('State/Province (required)') + '<span class="asteriskField">*</span>'
                    );
                    $('#opayo-payment-form #div_id_postal_code').find('label').html(
                      gettext('Zip/Postal Code (required)') + '<span class="asteriskField">*</span>'
                    );

                    _.each(states[country], function(value, key) {
                        $('#opayo-payment-form #id_state').append($('<option>', {value: value, text: key}));
                    });
                } else {
                    $($inputDiv).empty();
                    $('#opayo-payment-form #div_id_state').find('label').text('State/Province');
                    $('#opayo-payment-form #div_id_postal_code').find('label').text('Zip/Postal Code');
                    $($inputDiv).append(
                        '<input class="textinput textInput form-control" id="id_state"' +
                        'maxlength="2" name="state" type="text">'
                    );
                }
            });

            $('#opayo-payment-button').on('click', function(e) {
                e.preventDefault();
                _.each($('.help-block'), function(errorMsg) {
                    $(errorMsg).empty();  // Clear existing validation error messages.
                });
                $('#opayo-payment-form').attr('data-has-error', false);
                $('#opayo-payment-form .error-message').text('');

                if (self.extraInfoValidation()) {
                  self.onOpayoPaymentFormSubmit();
                }
            });

            $('#opayo-cancel-button').on('click', function (e) {
                self.closeExtraInfo();
            })
        },

        extraInfoValidation: function() {
            var self = this;
            var requiredFields = [
                    '#opayo-payment-form input[name=first_name]',
                    '#opayo-payment-form input[name=last_name]',
                    '#opayo-payment-form input[name=address_line1]',
                    '#opayo-payment-form input[name=city]',
                    '#opayo-payment-form select[name=country]'
                ],
                countriesWithRequiredStateAndPostalCodeValues = ['US', 'CA'],
                isValid = true

            if (countriesWithRequiredStateAndPostalCodeValues.indexOf($('#opayo-payment-form select[name=country]').val()) > -1) {
                requiredFields.push('#opayo-payment-form select[name=state]');
                requiredFields.push('#opayo-payment-form input[name=postal_code]');
            }

            _.each(requiredFields, function(field) {
                if ($(field).val() === '') {
                    isValid = false;
                    self.appendExtraInfoValidationErrorMsg($(field), gettext('This field is required'));
                    $('#opayo-payment-form').attr('data-has-error', true);
                }
            });

            // Focus the first element that has an error message.
            $('#opayo-payment-form .help-block > span').first().parents('.form-item').find('input').focus();

            return isValid
        },

        appendExtraInfoValidationErrorMsg: function(field, msg) {
            field.parentsUntil('form-item').find('~.help-block').append(
                '<span>' + msg + '</span>'
            );
        },

        renderErrors: function (data) {
            var self = this;
            $('#opayo-payment-form').attr('data-has-error', true);

            _.each(data.field_errors, function(value, key) {
                var $field = $(`#opayo-payment-form input[name=${key}]`)
                self.appendExtraInfoValidationErrorMsg($field, value);
                $('#opayo-payment-form').attr('data-has-error', true);
            })

            if (data.error) {
                $('#opayo-payment-form .error-message').text(data.error);
            }
        },

        onOpayoPaymentFormSubmit: function() {
            var data = {}
            this.removeEventListener();
            $('#opayo-payment-button .fa-spinner').removeClass('hidden');

            for (let field of $('#opayo-payment-form').serializeArray()) {
                data[field.name] = field.value;
            }

            $.ajax({
                url: this.transactionRegistrationUrl,
                method: 'POST',
                dataType: 'json',
                headers: {
                    'X-CSRFToken': Cookies.get('ecommerce_csrftoken')
                },
                data: data,
                success: this.onSuccess.bind(this),
                error: this.onFail.bind(this)
            });
        },

        closeExtraInfo: function () {
            this.addEventListenerButtonCheck();
            this.removeEventListener();
            $('.popup-opayo-extra-info').remove();
        },

        addEventListenerButtonCheck: function () {
          this.$buttonCheck.on('click', this.getExtraInfo.bind(this));
        },

        removeEventListener: function () {
            $('#opayo-payment-form select[name=country]').off();
            $('#opayo-payment-button').off();
            $('#opayo-cancel-button').off();
        },

    };
});
