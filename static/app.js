
const $ = (id) => document.getElementById(id);

const message = $("message");

async function api(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.detail || "Request failed");
    }

    return data;
}

async function loadVenues() {
    try {
        const venues = await api("/api/venues");

        $("venues").replaceChildren();
        $("venue").replaceChildren();

        venues.forEach((venue) => {
            const card = document.createElement("article");
            card.className = "venue";

            const title = document.createElement("h3");
            title.textContent = venue.name;

            const capacity = document.createElement("p");
            capacity.textContent =
                `Capacity: ${venue.capacity}`;

            const location = document.createElement("p");
            location.textContent =
                `Location: ${venue.location}`;

            card.append(title, capacity, location);
            $("venues").appendChild(card);

            const option = document.createElement("option");
            option.value = venue.id;
            option.textContent = venue.name;
            $("venue").appendChild(option);
        });
    } catch (error) {
        message.textContent = error.message;
    }
}

function bookingDetails() {
    return {
        venue_id: Number($("venue").value),
        date: $("date").value,
        start_time: $("start").value,
        end_time: $("end").value,
        attendees: Number($("attendees").value)
    };
}

function validate() {
    const b = bookingDetails();

    if (
        !b.venue_id || !b.date ||
        !b.start_time || !b.end_time ||
        !Number.isInteger(b.attendees) ||
        b.attendees < 1
    ) {
        throw new Error("Please complete all fields correctly.");
    }

    if (b.start_time >= b.end_time) {
        throw new Error("End time must be after start time.");
    }

    return b;
}

$("check").addEventListener("click", async () => {
    try {
        const b = validate();

        const params = new URLSearchParams({
            date: b.date,
            start_time: b.start_time,
            end_time: b.end_time
        });

        const result = await api(
            `/api/venues/${b.venue_id}/availability?${params}`
        );

        message.textContent = result.available
            ? "Venue is available for the requested time."
            : "Venue is not available at that time.";
    } catch (error) {
        message.textContent = error.message;
    }
});

$("bookingForm").addEventListener("submit", async (event) => {
    event.preventDefault();

    try {
        const b = validate();

        const result = await api("/api/bookings", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(b)
        });

        message.textContent =
            `Booking request #${result.id} submitted. Status: ${result.status}`;

        await loadBookings();
    } catch (error) {
        message.textContent = error.message;
    }
});

async function loadBookings() {
    try {
        const bookings = await api("/api/bookings");
        $("bookings").replaceChildren();

        bookings.forEach((booking) => {
            const item = document.createElement("li");
            item.textContent =
                `#${booking.id} — ${booking.venue_name} — ` +
                `${booking.date}, ${booking.start_time}-` +
                `${booking.end_time} — ${booking.status}`;

            $("bookings").appendChild(item);
        });
    } catch (error) {
        message.textContent = error.message;
    }
}

$("refresh").addEventListener("click", loadBookings);

loadVenues();
loadBookings();