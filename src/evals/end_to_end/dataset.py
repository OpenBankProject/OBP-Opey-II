from langsmith import Client

questions = [
    "Get me a list of banks on OBP",
    "Get me information on the user with email susan.be.29@example.com"
]

# These hard-coded answers are for the test sandbox deployment of OBP, this might create problems with the eval if the 
# deployment is changed, i.e. to apisandbox.openbankproject.com 
# The information in the answers will be quite different as the list of banks and the users will be different
# This is why end-to-end evals are not reccomended, as we need to eval that Opey will give the right answer given 
# pre-defined ToolMessages from endpoints and glossary retrieval tools, and/or the obp_requests tool

answers = [
    """
    Here's a list of some banks available on the Open Bank Project:

    1. **The Royal Bank of Scotland**
    - ID: rbs
    - Website: [www.red-bank-shoreditch.com](http://www.red-bank-shoreditch.com)
    - Logo: ![Logo](http://www.red-bank-shoreditch.com/logo.gif)

    2. **Test Bank**
    - ID: test-bank

    3. **Nordea Bank AB**
    - ID: nordea
    - Website: [www.nordea.com](http://www.nordea.com/)
    - Logo: ![Logo](http://logonoid.com/images/nordea-logo.jpg)

    4. **Hongkong and Shanghai Bank**
    - ID: hsbc-test

    5. **Erste Bank Test**
    - ID: erste-test

    6. **Deutche Bank Test**
    - ID: deutche-test

    7. **The Bank of X**
    - ID: obp-bankx-m
    - Website: [www.example.com](https://www.example.com)
    - Logo: ![Logo](https://static.openbankproject.com/images/bankx/bankx_logo.png)

    8. **The Bank of Y**
    - ID: obp-banky-m
    - Website: [www.example.com](https://www.example.com)
    - Logo: ![Logo](https://static.openbankproject.com/images/banky/banky_logo.png)

    9. **ABANCA CORPORACION BANCARIA, S.A.**
    - ID: at02-2080--01
    - Website: [WWW.ABANCA.COM/ES](http://WWW.ABANCA.COM/ES)
    - Logo: ![Logo](http://goo.gl/NS7W1U)

    10. **BANCO SANTANDER, S.A.**
        - ID: at02-0049--01
        - Website: [WWW.BANCOSANTANDER.ES](http://WWW.BANCOSANTANDER.ES)
        - Logo: ![Logo](https://goo.gl/T7fywl)

    This is just a selection of the banks available. If you need more information or a complete list, feel free to ask!
    """,
    """
    Here's the information for the user with the email **susan.be.29@example.com**:

    - **User ID**: 7d780516-fa85-463e-8a4f-3e5502a3d995
    - **Email**: susan.be.29@example.com
    - **Provider ID**: susan.be.29@example.com
    - **Provider**: [https://test.openbankproject.com](https://test.openbankproject.com)
    - **Username**: susan.be.29@example.com
    - **Entitlements**: None
    - **Is Deleted**: No
    - **Is Locked**: No

    If you need more details or have any other questions, feel free to ask!
    """

]

ls_client = Client()

dataset = ls_client.create_dataset(
    "opey-test-dataset",
    inputs=[{"question": q} for q in questions],
    outputs=[{"answers": a} for a in answers],
)