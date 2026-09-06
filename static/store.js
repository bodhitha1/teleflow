// Premium Store JS Logic

async function purchaseProduct(productId, requiredStars) {
    // Show loading alert
    Swal.fire({
        title: 'Processing Payment...',
        text: 'Waiting for Telegram confirmation. Do not close this window.',
        icon: 'info',
        allowOutsideClick: false,
        didOpen: () => {
            Swal.showLoading();
        }
    });

    try {
        const response = await fetch('/api/purchase', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                product_id: productId,
                required_stars: requiredStars,
                tenant_id: 'default'
            })
        });

        const data = await response.json();

        if (response.ok) {
            Swal.fire({
                title: 'Purchase Successful!',
                text: `You have successfully purchased ${productId.replace(/_/g, ' ')}.`,
                icon: 'success',
                confirmButtonColor: 'var(--accent-purple)'
            });
        } else {
            // Handle HTTP errors
            let errorMsg = data.detail || data.error || 'Payment failed.';
            if (typeof errorMsg === 'object') {
                errorMsg = errorMsg.error || errorMsg.status || JSON.stringify(errorMsg);
            }
            Swal.fire({
                title: 'Payment Failed',
                text: errorMsg,
                icon: 'error',
                confirmButtonColor: 'var(--status-error)'
            });
        }
    } catch (error) {
        console.error('Purchase error:', error);
        Swal.fire({
            title: 'Network Error',
            text: 'Could not connect to the server. Make sure you are logged into Telegram on the Dashboard first.',
            icon: 'error',
            confirmButtonColor: 'var(--status-error)'
        });
    }
}

async function refundProduct() {
    const chargeId = document.getElementById('refund-charge-id').value.trim();
    
    if (!chargeId) {
        Swal.fire({
            title: 'Error',
            text: 'Please enter a valid Charge ID',
            icon: 'warning'
        });
        return;
    }

    Swal.fire({
        title: 'Processing Refund...',
        allowOutsideClick: false,
        didOpen: () => {
            Swal.showLoading();
        }
    });

    try {
        const response = await fetch('/api/refund', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                charge_id: chargeId
            })
        });

        const data = await response.json();

        if (response.ok) {
            Swal.fire({
                title: 'Refund Issued!',
                text: `Refund for charge ${chargeId} has been successfully processed.`,
                icon: 'success',
                confirmButtonColor: 'var(--status-active)'
            });
        } else {
            let errorMsg = data.detail || data.error || 'Refund failed.';
            if (typeof errorMsg === 'object') {
                errorMsg = errorMsg.error || errorMsg.status || JSON.stringify(errorMsg);
            }
            Swal.fire({
                title: 'Refund Failed',
                text: errorMsg,
                icon: 'error'
            });
        }
    } catch (error) {
        console.error('Refund error:', error);
        Swal.fire({
            title: 'Error',
            text: 'Could not connect to the server.',
            icon: 'error'
        });
    }
}
