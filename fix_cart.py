path = r'c:\Users\jonah\Downloads\IS213 ESD\GroupProject\frontend\src\pages\MarketplaceCartPage.jsx'
with open(path, encoding='utf-8') as f:
    content = f.read()

# Build old block using exact bytes from the file (\u00e2\u02c6\u2019 = garbled minus)
old_block = (
    '                        <div className="cart-item__controls">\n'
    '                          <div className="quantity-stepper">\n'
    '                            <button\n'
    '                              type="button"\n'
    '                              onClick={() => onUpdateQuantity(entry.id, entry.quantity - 1)}\n'
    '                            >\n'
    '                              \u00e2\u02c6\u2019\n'
    '                            </button>\n'
    '                            <span>{entry.quantity}</span>\n'
    '                            <button\n'
    '                              type="button"\n'
    '                              onClick={() => onUpdateQuantity(entry.id, entry.quantity + 1)}\n'
    '                            >\n'
    '                              +\n'
    '                            </button>\n'
    '                          </div>\n'
    '\n'
    '                          <strong>\n'
    '                            {formatCurrency(entry.quantity * entry.unitPrice)}\n'
    '                          </strong>\n'
    '                        </div>'
)

new_block = (
    '                        <strong className="cart-item__price">\n'
    '                          {formatCurrency(entry.unitPrice)}\n'
    '                        </strong>'
)

if old_block in content:
    content = content.replace(old_block, new_block, 1)
    with open(path, encoding='utf-8', newline='') as f:
        pass
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS: stepper removed')
else:
    print('NOT FOUND - checking partial...')
    idx = content.find('quantity-stepper')
    print(repr(content[idx:idx+300]))
