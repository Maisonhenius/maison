/* Maison Henius - Cart (localStorage + Supabase sync)
   Guest users: localStorage only
   Logged-in users: localStorage + server sync */

var MaisonCart = (function() {
  var STORAGE_KEY = 'maison_cart';

  function _getAuth() {
    try {
      var auth = JSON.parse(localStorage.getItem('maison_auth'));
      return auth && auth.access_token ? auth : null;
    } catch (e) { return null; }
  }

  function _apiHeaders() {
    var auth = _getAuth();
    var headers = { 'Content-Type': 'application/json' };
    if (auth) headers['Authorization'] = 'Bearer ' + auth.access_token;
    return headers;
  }

  function _read() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
    } catch (e) { return []; }
  }

  function _write(items) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    _updateBadge();
  }

  function _updateBadge() {
    var badges = document.querySelectorAll('.cart-badge');
    var count = getCount();
    badges.forEach(function(badge) {
      badge.textContent = count;
      badge.style.display = count > 0 ? 'flex' : 'none';
    });
  }

  var _justSynced = false;

  function _showToast(message) {
    var existing = document.querySelector('.maison-toast');
    if (existing) existing.parentNode.removeChild(existing);
    var toast = document.createElement('div');
    toast.className = 'maison-toast';
    toast.textContent = message;
    toast.style.cssText = 'position:fixed;bottom:2rem;left:50%;transform:translateX(-50%);background:#0a0a08;color:#f5f0e8;font-family:Montserrat,sans-serif;font-size:0.75rem;font-weight:400;letter-spacing:0.05em;padding:0.8rem 1.8rem;border-radius:4px;box-shadow:0 4px 20px rgba(0,0,0,0.3);z-index:9999;opacity:0;transition:opacity 0.3s ease;border:1px solid rgba(233,219,144,0.2);';
    document.body.appendChild(toast);
    requestAnimationFrame(function() { toast.style.opacity = '1'; });
    setTimeout(function() {
      toast.style.opacity = '0';
      setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
    }, 2000);
  }

  function addItem(product) {
    /* product: { id, name, family, price, image, quantity? } */
    var items = _read();
    var existing = items.find(function(item) { return item.id === product.id; });
    if (existing) {
      existing.quantity += (product.quantity || 1);
    } else {
      items.push({
        id: product.id,
        name: product.name,
        family: product.family || '',
        price: product.price || 284,
        image: product.image || '',
        quantity: product.quantity || 1
      });
    }
    _write(items);

    // Sync to server if logged in (fire and forget)
    if (_getAuth()) {
      fetch('/api/cart', {
        method: 'POST',
        headers: _apiHeaders(),
        body: JSON.stringify({
          product_id: product.id,
          product_name: product.name,
          product_family: product.family || '',
          product_price: product.price || 284,
          product_image: product.image || '',
          quantity: product.quantity || 1
        })
      }).catch(function() {});
    }

    _showToast(product.name + ' added to cart');
    return items;
  }

  function removeItem(productId) {
    var items = _read().filter(function(item) { return item.id !== productId; });
    _write(items);

    // Sync to server if logged in
    if (_getAuth()) {
      // Find the server item by product_id and delete it
      fetch('/api/cart', { headers: _apiHeaders() })
        .then(function(r) { return r.json(); })
        .then(function(data) {
          var serverItem = (data.items || []).find(function(i) { return i.product_id === productId; });
          if (serverItem) {
            fetch('/api/cart/' + serverItem.id, { method: 'DELETE', headers: _apiHeaders() }).catch(function() {});
          }
        }).catch(function() {});
    }

    return items;
  }

  function updateQuantity(productId, quantity) {
    var items = _read();
    var item = items.find(function(i) { return i.id === productId; });
    if (item) {
      if (quantity <= 0) {
        return removeItem(productId);
      }
      item.quantity = quantity;
      _write(items);

      // Sync to server if logged in
      if (_getAuth()) {
        fetch('/api/cart', { headers: _apiHeaders() })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            var serverItem = (data.items || []).find(function(i) { return i.product_id === productId; });
            if (serverItem) {
              fetch('/api/cart/' + serverItem.id, {
                method: 'PATCH',
                headers: _apiHeaders(),
                body: JSON.stringify({ quantity: quantity })
              }).catch(function() {});
            }
          }).catch(function() {});
      }
    }
    return items;
  }

  function getCart() { return _read(); }
  function getCount() { return _read().reduce(function(sum, item) { return sum + item.quantity; }, 0); }
  function getTotal() { return _read().reduce(function(sum, item) { return sum + (item.price * item.quantity); }, 0); }

  function clear() {
    _write([]);
    // Clear server cart too
    if (_getAuth()) {
      fetch('/api/cart', { headers: _apiHeaders() })
        .then(function(r) { return r.json(); })
        .then(function(data) {
          (data.items || []).forEach(function(item) {
            fetch('/api/cart/' + item.id, { method: 'DELETE', headers: _apiHeaders() }).catch(function() {});
          });
        }).catch(function() {});
    }
  }

  function sync() {
    /* Called after login/signup. Sends localStorage cart to server, gets merged result back */
    var auth = _getAuth();
    if (!auth) return Promise.resolve();

    var localItems = _read();
    return fetch('/api/cart/sync', {
      method: 'POST',
      headers: _apiHeaders(),
      body: JSON.stringify({ items: localItems })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.items) {
        // Convert server format to localStorage format
        var merged = data.items.map(function(item) {
          return {
            id: item.product_id,
            name: item.product_name,
            family: item.product_family || '',
            price: item.product_price || 284,
            image: item.product_image || '',
            quantity: item.quantity || 1
          };
        });
        _write(merged);
        _justSynced = true;
      }
    })
    .catch(function() {});
  }

  function loadFromServer() {
    /* Called on page load when logged in. Fetches server cart into localStorage */
    // Skip on /checkout/success — the route + page script clear the cart, and
    // an in-flight server sync would race the clear and repopulate localStorage.
    if (window.location.pathname === '/checkout/success') return;
    if (_justSynced) { _justSynced = false; return; }
    var auth = _getAuth();
    if (!auth) return;

    fetch('/api/cart', { headers: _apiHeaders() })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.items && data.items.length > 0) {
          var serverCart = data.items.map(function(item) {
            return {
              id: item.product_id,
              name: item.product_name,
              family: item.product_family || '',
              price: item.product_price || 284,
              image: item.product_image || '',
              quantity: item.quantity || 1
            };
          });
          // Merge: server wins for items that exist on both, keep local-only items
          var localItems = _read();
          var serverIds = serverCart.map(function(i) { return i.id; });
          var localOnly = localItems.filter(function(i) { return serverIds.indexOf(i.id) === -1; });
          _write(serverCart.concat(localOnly));
        }
      })
      .catch(function() {});
  }

  // Init badge on page load + load server cart if logged in
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      _updateBadge();
      loadFromServer();
    });
  } else {
    _updateBadge();
    loadFromServer();
  }

  return {
    addItem: addItem,
    removeItem: removeItem,
    updateQuantity: updateQuantity,
    getCart: getCart,
    getCount: getCount,
    getTotal: getTotal,
    clear: clear,
    sync: sync,
    loadFromServer: loadFromServer
  };
})();
