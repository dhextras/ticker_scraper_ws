let socket;
let pushEnabled = false;
let allMessages = [];
let currentPage = 1;
let messagesPerPage = 10;
let currentSort = { field: "timestamp", ascending: false };
let config = null;

window.initApp = async function () {
  try {
    const response = await fetch("/config.js", {
      headers: {
        Authorization: `Bearer ${auth.getToken()}`,
      },
    });

    if (!response.ok) {
      throw new Error("Failed to load config");
    }

    const configText = await response.text();
    eval(configText);

    if (!window.config) {
      throw new Error("Config not found");
    }

    config = window.config;
  } catch (error) {
    console.error("Failed to load config:", error);
    auth.logout();
    return;
  }

  const endDate = document.getElementById("end-date");
  const typeDropdown = document.getElementById("type");
  const pageSize = document.getElementById("page-size");
  const searchInput = document.getElementById("search");
  const startDate = document.getElementById("start-date");
  const senderDropdown = document.getElementById("sender");
  const sendButton = document.getElementById("send-button");
  const menuButton = document.getElementById("menu-button");
  const menuDropdown = document.getElementById("menu-dropdown");
  const senderFilter = document.getElementById("sender-filter");
  const messageTarget = document.getElementById("message-target");
  const messageTableBody = document.getElementById("message-table-body");

  // Get current target from hash or use first target as default
  const getCurrentTarget = () => {
    const hash = window.location.hash;
    const target = Object.entries(config.targets).find(
      ([_, value]) => value.path === hash,
    );

    if (!target) {
      const defaultTarget = Object.entries(config.targets)[0];
      window.location.hash = defaultTarget[1].path.slice(1);
      return defaultTarget[0];
    }

    return target[0];
  };

  // Populate sender dropdowns
  Object.entries(config.senders).forEach(([key, { name }]) => {
    [senderDropdown, senderFilter].forEach((dropdown) => {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = name;
      dropdown.appendChild(option);
    });
  });

  // Populate target dropdown
  Object.entries(config.targets).forEach(([key, { name, path }]) => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = name;
    messageTarget.appendChild(option);
  });

  // Populate menu
  Object.entries(config.targets).forEach(([key, { name, path }]) => {
    const menuItem = document.createElement("a");
    menuItem.href = path;
    menuItem.className = "menu-item";
    menuItem.textContent = name;

    if (key === getCurrentTarget()) {
      menuItem.classList.add("active");
    }

    menuDropdown.appendChild(menuItem);
  });

  // Handle hash changes
  window.addEventListener("hashchange", () => {
    const currentTarget = getCurrentTarget();
    if (!currentTarget) return; // Exit if redirect is happening

    currentPage = 1;

    // Update active menu item
    document.querySelectorAll(".menu-item").forEach((item) => {
      const targetEntry = Object.entries(config.targets).find(
        ([key, _]) => key === currentTarget,
      );
      item.classList.toggle(
        "active",
        item.getAttribute("href") === targetEntry[1].path,
      );
    });

    refreshTable();
  });

  // Initial redirect if no hash
  if (!window.location.hash) {
    window.location.hash =
      config.targets[Object.keys(config.targets)[0]].path.slice(1);
  }

  // Toggle menu
  menuButton.addEventListener("click", (e) => {
    e.stopPropagation();
    menuDropdown.classList.toggle("show");
  });

  // Close menu when clicking outside
  document.addEventListener("click", (e) => {
    if (!menuDropdown.contains(e.target) && !menuButton.contains(e.target)) {
      menuDropdown.classList.remove("show");
    }
  });

  // Setup event listeners on tool bar functions
  endDate.addEventListener("change", refreshTable);
  pageSize.addEventListener("change", refreshTable);
  startDate.addEventListener("change", refreshTable);
  searchInput.addEventListener("input", refreshTable);
  senderFilter.addEventListener("change", refreshTable);

  // Setup sorting
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const field = th.dataset.sort;
      if (currentSort.field === field) {
        currentSort.ascending = !currentSort.ascending;
      } else {
        currentSort.field = field;
        currentSort.ascending = true;
      }
      refreshTable();
    });
  });

  requestNotificationPermission();

  // Connect to WebSocket with authentication
  const wsUrl = new URL(window.env.WEBSOCKET_URL);
  wsUrl.searchParams.set("token", auth.getToken());
  socket = new WebSocket(wsUrl.toString());

  socket.onopen = function () {
    console.log("Connected to WebSocket server");
    if (pushEnabled) {
      new Notification("WebSocket Connected", {
        body: "You are now connected to the WebSocket server",
      });
    }

    socket.send(JSON.stringify({ request_old_messages: true }));
  };

  socket.onmessage = function (event) {
    const data = JSON.parse(event.data);
    if (Array.isArray(data)) {
      allMessages = data;
    } else {
      allMessages.unshift(data);
    }
    refreshTable();
  };

  socket.onerror = function (error) {
    console.error("WebSocket error:", error);
  };

  socket.onclose = function (event) {
    if (event.code === 1008) {
      // Unauthorized
      console.log("WebSocket connection unauthorized");
      auth.logout();
    }
  };

  sendButton.addEventListener("click", function () {
    const sender = senderDropdown.value;
    const name = `${config.senders[sender]?.name || sender} - TEST`;
    const messageType = typeDropdown.value;
    const target = messageTarget.value;

    if (sender && messageType) {
      const data = {
        sender,
        name,
        type: messageType,
        ticker: "TEST_IGNORE",
      };

      if (target) data.target = target;
      socket.send(JSON.stringify(data));
      senderDropdown.selectedIndex = 0;
      typeDropdown.selectedIndex = 0;
      messageTarget.selectedIndex = 0;
    } else {
      alert("Choose a Name and a Type before sending.");
    }
  });

  function refreshTable() {
    messagesPerPage = parseInt(pageSize.value);
    const currentTarget = getCurrentTarget();

    // Apply filters
    let filteredMessages = allMessages.filter((message) => {
      const searchTerm = searchInput.value.toLowerCase();
      const senderFilterValue = senderFilter.value;
      const startDateValue = startDate.value ? new Date(startDate.value) : null;
      const endDateValue = endDate.value ? new Date(endDate.value) : null;

      const targetMatches =
        currentTarget === "unknown"
          ? message.target && message.target in Object.keys(config.targets)
          : !message.target
            ? true
            : message.target === currentTarget;

      return (
        (!searchTerm || message.ticker.toLowerCase().includes(searchTerm)) &&
        (!senderFilterValue || message.sender === senderFilterValue) &&
        (!startDateValue || new Date(message.timestamp) >= startDateValue) &&
        (!endDateValue || new Date(message.timestamp) <= endDateValue) &&
        targetMatches
      );
    });

    // Sort messages
    filteredMessages.sort((a, b) => {
      let aValue = a[currentSort.field];
      let bValue = b[currentSort.field];

      if (currentSort.field === "timestamp") {
        aValue = new Date(aValue);
        bValue = new Date(bValue);
      }

      const comparison = aValue < bValue ? -1 : aValue > bValue ? 1 : 0;
      return currentSort.ascending ? comparison : -comparison;
    });

    // Update pagination
    const totalPages = Math.ceil(filteredMessages.length / messagesPerPage);
    currentPage = Math.min(currentPage, totalPages);
    currentPage = currentPage === 0 && totalPages > 0 ? 1 : currentPage;
    updatePagination(totalPages);

    // Display current page
    const start = (currentPage - 1) * messagesPerPage;
    const end = start + parseInt(messagesPerPage);
    const pageMessages = filteredMessages.slice(start, end);

    // Clear and repopulate table
    messageTableBody.innerHTML = "";
    pageMessages.forEach((message) => {
      const isNewMessage =
        !message.old_message && message.old_message === false;

      addRowToTable(
        message.name,
        message.sender,
        message.type,
        message.ticker,
        message.timestamp,
      );

      if (isNewMessage) {
        if (pushEnabled) {
          new Notification(message.name, {
            body: `${message.type} ${message.ticker || "N/A"}`,
          });
        }
      }
    });

    // Update sort indicators
    document.querySelectorAll("th[data-sort]").forEach((th) => {
      const field = th.dataset.sort;
      th.textContent = th.textContent.replace(" ↑", "").replace(" ↓", "");
      if (field === currentSort.field) {
        th.textContent += currentSort.ascending ? " ↑" : " ↓";
      }
    });
  }

  function updatePagination(totalPages) {
    const pagination = document.getElementById("pagination");
    pagination.innerHTML = "";

    if (totalPages <= 1) return;

    // Previous button
    addPaginationButton("«", currentPage > 1, () => {
      currentPage--;
      refreshTable();
    });

    // Calculate visible page numbers
    let startPage = Math.max(1, currentPage - 2);
    let endPage = Math.min(totalPages, startPage + 4);
    startPage = Math.max(1, endPage - 4);

    if (startPage > 1) {
      addPaginationButton("1", true, () => {
        currentPage = 1;
        refreshTable();
      });
      if (startPage > 2) {
        pagination.appendChild(document.createTextNode("..."));
      }
    }

    for (let i = startPage; i <= endPage; i++) {
      addPaginationButton(
        i.toString(),
        true,
        () => {
          currentPage = i;
          refreshTable();
        },
        i === currentPage,
      );
    }

    if (endPage < totalPages) {
      if (endPage < totalPages - 1) {
        pagination.appendChild(document.createTextNode("..."));
      }
      addPaginationButton(totalPages.toString(), true, () => {
        currentPage = totalPages;
        refreshTable();
      });
    }

    // Next button
    addPaginationButton("»", currentPage < totalPages, () => {
      currentPage++;
      refreshTable();
    });
  }

  function addPaginationButton(text, enabled, onClick, isActive = false) {
    const button = document.createElement("button");
    button.textContent = text;
    button.disabled = !enabled;
    if (isActive) button.classList.add("active");
    button.addEventListener("click", onClick);
    document.getElementById("pagination").appendChild(button);
  }

  function addRowToTable(name, sender, type, ticker, timestamp) {
    const row = document.createElement("tr");
    const senderCell = document.createElement("td");
    const typeCell = document.createElement("td");
    const tickerCell = document.createElement("td");
    const timestampCell = document.createElement("td");

    senderCell.textContent = name || config.senders[sender]?.name || sender;
    typeCell.textContent = type;
    tickerCell.textContent = ticker || "N/A";
    timestampCell.textContent = formatDate(timestamp);

    row.style.backgroundColor = config.senders[sender]?.color || "#FFFFFF";

    row.appendChild(senderCell);
    row.appendChild(typeCell);
    row.appendChild(tickerCell);
    row.appendChild(timestampCell);
    messageTableBody.appendChild(row);
  }

  async function requestNotificationPermission() {
    if (!("Notification" in window)) {
      alert("This browser does not support desktop notifications");
      return;
    }

    try {
      const permission = await Notification.requestPermission();
      pushEnabled = permission === "granted";
      if (!permission) alert("Notification permission denied");
    } catch (error) {
      console.error("Error requesting notification permission:", error);
    }
  }

  function formatDate(timestamp) {
    const tempDate = timestamp ? new Date(timestamp) : new Date();
    return (
      `${tempDate.getMonth() + 1}/${tempDate.getDate()}/${tempDate.getFullYear()}, ` +
      `${tempDate.getHours() % 12 || 12}:${tempDate
        .getMinutes()
        .toString()
        .padStart(2, "0")}:${tempDate
        .getSeconds()
        .toString()
        .padStart(2, "0")}.${tempDate.getMilliseconds()} ` +
      `${tempDate.getHours() >= 12 ? "PM" : "AM"}`
    );
  }
};
