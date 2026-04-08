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

  // Badge nodes are queried once per render instead of on every _updateBadge call.
  // Re-queried on Turbo navigation since the DOM is swapped.
  var _cachedBadges = null;
  function _getBadges() {
    if (!_cachedBadges || !_cachedBadges.length || !document.contains(_cachedBadges[0])) {
      _cachedBadges = document.querySelectorAll('.cart-badge');
    }
    return _cachedBadges;
  }
  document.addEventListener('turbo:load', function() { _cachedBadges = null; });

  function _updateBadge() {
    var badges = _getBadges();
    var count = getCount();
    for (var i = 0; i < badges.length; i++) {
      badges[i].textContent = count;
      badges[i].style.display = count > 0 ? 'flex' : 'none';
    }
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

  // Helper: find a local item's server row id. Falls back to a one-off GET
  // if we don't have it cached (e.g. item was written by an older version of
  // this script that didn't store serverId). New writes always cache it.
  function _findServerItemId(productId) {
    var items = _read();
    var item = items.find(function(i) { return i.id === productId; });
    if (item && item.serverId) return Promise.resolve(item.serverId);
    // Legacy fallback — should rarely hit after a user adds or edits anything once.
    return fetch('/api/cart', { headers: _apiHeaders() })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var match = (data.items || []).find(function(i) { return i.product_id === productId; });
        return match ? match.id : null;
      });
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

    // Sync to server if logged in. The POST /api/cart endpoint returns the full
    // merged cart — we use the response to cache each item's server id in
    // localStorage so subsequent update/delete calls only need ONE round-trip
    // (instead of the previous GET+DELETE / GET+PATCH pattern).
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
      })
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (!data || !data.items) return;
        // Merge server ids back into localStorage
        var local = _read();
        var byPid = {};
        data.items.forEach(function(srv) { byPid[srv.product_id] = srv.id; });
        local.forEach(function(li) {
          if (byPid[li.id]) li.serverId = byPid[li.id];
        });
        localStorage.setItem(STORAGE_KEY, JSON.stringify(local));
      })
      .catch(function() {});
    }

    _showToast(product.name + ' added to cart');
    return items;
  }

  function removeItem(productId) {
    var priorItems = _read();
    var removedItem = priorItems.find(function(i) { return i.id === productId; });
    var items = priorItems.filter(function(item) { return item.id !== productId; });
    _write(items);

    // Sync to server if logged in — use cached serverId if available (one round-trip
    // instead of GET+DELETE).
    if (_getAuth() && removedItem) {
      if (removedItem.serverId) {
        fetch('/api/cart/' + removedItem.serverId, { method: 'DELETE', headers: _apiHeaders() }).catch(function() {});
      } else {
        _findServerItemId(productId).then(function(serverId) {
          if (serverId) fetch('/api/cart/' + serverId, { method: 'DELETE', headers: _apiHeaders() }).catch(function() {});
        }).catch(function() {});
      }
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

      // Sync to server if logged in — use cached serverId.
      if (_getAuth()) {
        var patch = function(serverId) {
          if (!serverId) return;
          fetch('/api/cart/' + serverId, {
            method: 'PATCH',
            headers: _apiHeaders(),
            body: JSON.stringify({ quantity: quantity })
          }).catch(function() {});
        };
        if (item.serverId) patch(item.serverId);
        else _findServerItemId(productId).then(patch).catch(function() {});
      }
    }
    return items;
  }

  function getCart() { return _read(); }
  function getCount() { return _read().reduce(function(sum, item) { return sum + item.quantity; }, 0); }
  function getTotal() { return _read().reduce(function(sum, item) { return sum + (item.price * item.quantity); }, 0); }

  function clear() {
    var priorItems = _read();
    _write([]);
    // Clear server cart too — use cached serverIds so we avoid the GET round-trip.
    // If any items are missing a cached serverId (legacy), fall back to GET.
    if (_getAuth() && priorItems.length) {
      var missingCachedId = priorItems.some(function(i) { return !i.serverId; });
      if (missingCachedId) {
        fetch('/api/cart', { headers: _apiHeaders() })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            (data.items || []).forEach(function(item) {
              fetch('/api/cart/' + item.id, { method: 'DELETE', headers: _apiHeaders() }).catch(function() {});
            });
          }).catch(function() {});
      } else {
        priorItems.forEach(function(item) {
          fetch('/api/cart/' + item.serverId, { method: 'DELETE', headers: _apiHeaders() }).catch(function() {});
        });
      }
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
      .then(function(r) {
        if (r.status === 401) {
          // Token is stale/expired — evict it so future navigations bail early
          // (without this, every Turbo nav would re-hit /api/cart and re-401)
          localStorage.removeItem('maison_auth');
          return null;
        }
        return r.json();
      })
      .then(function(data) {
        if (!data || !data.items) return;  // request failed or unauthenticated — keep localStorage as-is
        var serverCart = data.items.map(function(item) {
          return {
            id: item.product_id,
            serverId: item.id,  // cache server row id for fewer round-trips on mutate
            name: item.product_name,
            family: item.product_family || '',
            price: item.product_price || 284,
            image: item.product_image || '',
            quantity: item.quantity || 1
          };
        });
        // For logged-in users the server cart is authoritative.
        // Empty server cart → clear localStorage (fixes stale cart after checkout when
        // user never sees /checkout/success). Guest→login merge is handled by sync().
        _write(serverCart);
      })
      .catch(function() {});
  }

  // Init: update the badge immediately (reads from localStorage — synchronous, cheap)
  // then defer the server sync until the browser is idle, so it doesn't compete
  // with first-paint resources (fonts, hero video, critical CSS).
  function _scheduleServerSync() {
    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(loadFromServer, { timeout: 2000 });
    } else {
      setTimeout(loadFromServer, 300);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      _updateBadge();
      _scheduleServerSync();
    });
  } else {
    _updateBadge();
    _scheduleServerSync();
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
