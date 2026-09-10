#include "WebShooterComponent.h"

#include "CableComponent.h"
#include "Components/PrimitiveComponent.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "WebSlingerMovementComponent.h"

UWebShooterComponent::UWebShooterComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	// After movement, so the cable is drawn from where the character ended up
	// rather than a frame behind it.
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

void UWebShooterComponent::BeginPlay()
{
	Super::BeginPlay();
	if (Cable)
	{
		Cable->SetVisibility(false);
	}
}

UWebSlingerMovementComponent* UWebShooterComponent::GetSlingerMovement() const
{
	const ACharacter* Char = Cast<ACharacter>(GetOwner());
	return Char ? Cast<UWebSlingerMovementComponent>(Char->GetCharacterMovement()) : nullptr;
}

// ---------------------------------------------------------------------------
// Anchor search
// ---------------------------------------------------------------------------

bool UWebShooterComponent::IsValidAnchor(const FHitResult& Hit) const
{
	if (!Hit.IsValidBlockingHit() || Hit.Distance < MinAnchorDistance)
	{
		return false;
	}

	const AActor* HitActor = Hit.GetActor();
	if (!HitActor || HitActor->ActorHasTag(NoAnchorTag))
	{
		return false;
	}

	// Anything that can move will not hold a swing, and dragging a physics prop
	// toward you reads as a bug rather than a feature.
	const UPrimitiveComponent* HitComp = Hit.GetComponent();
	if (HitComp && HitComp->IsSimulatingPhysics())
	{
		return false;
	}

	const AActor* Owner = GetOwner();
	if (Owner && Hit.ImpactPoint.Z < Owner->GetActorLocation().Z + MinAnchorHeight)
	{
		return false;
	}

	return true;
}

bool UWebShooterComponent::FindAnchor(FVector& OutAnchor) const
{
	const UWorld* World = GetWorld();
	const AActor* Owner = GetOwner();
	if (!World || !Owner)
	{
		return false;
	}

	const FVector Start = GetComponentLocation();
	const FVector Forward = GetForwardVector();
	const FVector Right = GetRightVector();
	const FVector Up = GetUpVector();

	FCollisionQueryParams Params(SCENE_QUERY_STAT(WebAnchorSearch), false, Owner);
	const FCollisionShape Probe = FCollisionShape::MakeSphere(ProbeRadius);

	bool bFound = false;
	float BestScore = TNumericLimits<float>::Max();
	const int32 Rings = FMath::Max(0, AssistRings);

	for (int32 Ring = 0; Ring <= Rings; ++Ring)
	{
		const float RingDegrees = (Rings > 0) ? AssistConeAngle * (static_cast<float>(Ring) / static_cast<float>(Rings)) : 0.f;
		const float RingRadians = FMath::DegreesToRadians(RingDegrees);
		const int32 Samples = (Ring == 0) ? 1 : FMath::Max(1, AssistSamplesPerRing);

		for (int32 Sample = 0; Sample < Samples; ++Sample)
		{
			// Offset each ring's phase so samples do not stack into spokes,
			// which would leave blind wedges between them.
			const float Theta = (2.f * PI) * (static_cast<float>(Sample) / static_cast<float>(Samples)) + Ring * 0.4f;
			const FVector Offset = (Right * FMath::Cos(Theta) + Up * FMath::Sin(Theta)) * FMath::Sin(RingRadians);
			const FVector Dir = (Forward * FMath::Cos(RingRadians) + Offset).GetSafeNormal();

			FHitResult Hit;
			const bool bHit = World->SweepSingleByChannel(
				Hit, Start, Start + Dir * MaxAnchorDistance, FQuat::Identity, AnchorChannel, Probe, Params);

			if (!bHit || !IsValidAnchor(Hit))
			{
				continue;
			}

			const float Score = RingDegrees * AimPenalty + Hit.Distance * DistancePenalty;
			if (Score < BestScore)
			{
				BestScore = Score;
				OutAnchor = Hit.ImpactPoint;
				bFound = true;
			}
		}
	}

	return bFound;
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

void UWebShooterComponent::FireWeb()
{
	UWebSlingerMovementComponent* Move = GetSlingerMovement();
	if (!Move)
	{
		return;
	}

	FVector AnchorPoint;
	if (!FindAnchor(AnchorPoint))
	{
		return;
	}

	if (Move->BeginSwing(AnchorPoint) && Cable)
	{
		Cable->SetVisibility(true);
	}
}

void UWebShooterComponent::ReleaseWeb()
{
	if (UWebSlingerMovementComponent* Move = GetSlingerMovement())
	{
		Move->EndSwing(true);
	}
	if (Cable)
	{
		Cable->SetVisibility(false);
	}
}

void UWebShooterComponent::ZipToTarget()
{
	ACharacter* Char = Cast<ACharacter>(GetOwner());
	UWebSlingerMovementComponent* Move = GetSlingerMovement();
	if (!Char || !Move)
	{
		return;
	}

	FVector AnchorPoint;
	if (!FindAnchor(AnchorPoint))
	{
		return;
	}

	// A zip aimed flat at a ledge lands you in its face. The lift turns it into
	// an arc that clears the lip.
	const FVector Dir = (AnchorPoint - Char->GetActorLocation()).GetSafeNormal();
	Move->EndSwing(false);
	Char->LaunchCharacter(Dir * ZipSpeed + FVector::UpVector * ZipLift, true, true);
}

// ---------------------------------------------------------------------------
// Tick
// ---------------------------------------------------------------------------

void UWebShooterComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	const UWebSlingerMovementComponent* Move = GetSlingerMovement();
	const bool bSwinging = Move && Move->HasWeb();

	if (bSwinging)
	{
		// While attached the reticle should show the live anchor, not whatever
		// the player happens to be looking at.
		bHasTarget = true;
		CurrentTarget = Move->GetAnchor();
	}
	else
	{
		FVector Found;
		bHasTarget = FindAnchor(Found);
		CurrentTarget = bHasTarget ? Found : FVector::ZeroVector;
	}

	UpdateCableVisual();
}

void UWebShooterComponent::UpdateCableVisual()
{
	if (!Cable)
	{
		return;
	}

	const UWebSlingerMovementComponent* Move = GetSlingerMovement();
	if (!Move || !Move->HasWeb())
	{
		Cable->SetVisibility(false);
		return;
	}

	Cable->SetVisibility(true);
	// EndLocation is component space; the anchor is a fixed world point, so it
	// has to be re-resolved every frame as the character swings past it.
	Cable->EndLocation = Cable->GetComponentTransform().InverseTransformPosition(Move->GetAnchor());
	Cable->CableLength = FMath::Max(1.f, Move->GetRopeLength());
}
